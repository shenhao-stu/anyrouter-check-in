importScripts('libsodium.min.js', 'libsodium-wrappers.min.js');

const ALARM_NAME = 'cookieSync';

const Logger = {
  async log(level, message, details = null) {
    const timestamp = new Date().toISOString();
    const logEntry = { timestamp, level, message, details };
    console.log(`[${level}] ${message}`, details || '');
    const { logs = [] } = await chrome.storage.local.get(['logs']);
    logs.unshift(logEntry);
    if (logs.length > 100) logs.splice(100);
    await chrome.storage.local.set({ logs });
  },
  info(msg, d) { return this.log('INFO', msg, d); },
  error(msg, d) { return this.log('ERROR', msg, d); },
  success(msg, d) { return this.log('SUCCESS', msg, d); },
  async getLogs() { return (await chrome.storage.local.get(['logs'])).logs || []; },
  async clearLogs() { await chrome.storage.local.set({ logs: [] }); }
};

chrome.runtime.onInstalled.addListener(async () => {
  await Logger.info('AnyRouter Cookie Updater installed');
  await setupAlarm();
});

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'updateConfig') {
    setupAlarm().then(() => Logger.info('Config updated, alarm reset'));
  } else if (request.action === 'syncNow') {
    syncAllAccounts().then(sendResponse).catch(e => sendResponse({ success: false, error: e.message }));
    return true;
  } else if (request.action === 'testAccount') {
    testOneAccount(request.account).then(sendResponse).catch(e => sendResponse({ success: false, error: e.message }));
    return true;
  } else if (request.action === 'getLogs') {
    Logger.getLogs().then(logs => sendResponse({ success: true, logs }));
    return true;
  } else if (request.action === 'clearLogs') {
    Logger.clearLogs().then(() => sendResponse({ success: true }));
    return true;
  }
});

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name !== ALARM_NAME) return;
  await Logger.info('Scheduled sync triggered');
  const result = await syncAllAccounts();
  const title = result.success ? '✅ Cookie 同步完成' : '❌ Cookie 同步失败';
  chrome.notifications.create({ type: 'basic', iconUrl: 'icon.png', title, message: result.summary || result.error || '' });
});

async function setupAlarm() {
  await chrome.alarms.clear(ALARM_NAME);
  const { refreshInterval = 360 } = await chrome.storage.sync.get(['refreshInterval']);
  chrome.alarms.create(ALARM_NAME, { periodInMinutes: refreshInterval });
  await Logger.info(`Alarm set: every ${refreshInterval} minutes`);
}

async function getConfig() {
  return chrome.storage.sync.get([
    'githubToken', 'repoOwner', 'repoName', 'environmentName', 'accounts', 'refreshInterval'
  ]);
}

async function syncAllAccounts() {
  _cachedRepoId = null;
  const config = await getConfig();
  if (!config.githubToken || !config.repoOwner || !config.repoName) {
    await Logger.error('GitHub configuration incomplete');
    return { success: false, error: 'GitHub 配置不完整' };
  }

  let accounts;
  try {
    accounts = typeof config.accounts === 'string' ? JSON.parse(config.accounts) : config.accounts;
  } catch (e) {
    await Logger.error('Failed to parse accounts config', { error: e.message });
    return { success: false, error: '账号配置格式错误' };
  }

  if (!Array.isArray(accounts) || accounts.length === 0) {
    await Logger.error('No accounts configured');
    return { success: false, error: '未配置任何账号' };
  }

  const results = [];
  for (const account of accounts) {
    const result = await syncOneAccount(config, account);
    results.push(result);
  }

  // Sync custom providers so checkin.py knows how to route each site
  await syncProvidersSecret(config, accounts);

  const okCount = results.filter(r => r.success).length;
  const summary = `${okCount}/${results.length} 账号同步成功`;
  await Logger.info('Sync completed', { summary });
  return { success: okCount > 0, summary, results };
}

async function testOneAccount(account) {
  if (!account || !account.domain) {
    return { success: false, error: '缺少 domain' };
  }

  const result = await syncOneAccount(null, account, { dryRun: true });
  if (!result.success) {
    return result;
  }

  const parts = [`cookie=${result.cookieName}`];
  if (result.api_user) parts.push(`api_user=${result.api_user}`);
  if (result.provider) parts.push(`provider=${result.provider}`);
  const partial = !result.api_user;

  return {
    success: true,
    summary: parts.join(' · '),
    partial,
    result,
  };
}

// Build and push PROVIDERS secret for all non-builtin domains
async function syncProvidersSecret(config, accounts) {
  const { customProviders: stored = {} } = await chrome.storage.local.get(['customProviders']);
  const providersMap = Object.fromEntries(
    Object.entries(stored).filter(([providerName]) => !BUILTIN_PROVIDERS.has(providerName))
  );

  for (const account of (accounts || [])) {
    if (!account.domain) continue;
    const providerName = getProviderName(account.domain);
    if (BUILTIN_PROVIDERS.has(providerName)) continue;
    if (!providersMap[providerName]) {
      providersMap[providerName] = { domain: account.domain.replace(/\/$/, '') };
    }
  }

  await chrome.storage.local.set({ customProviders: providersMap });

  try {
    await pushToGitHubSecret(config, 'PROVIDERS', JSON.stringify(providersMap));
    await Logger.success('PROVIDERS secret updated', { providers: Object.keys(providersMap) });
  } catch (e) {
    await Logger.error('Failed to update PROVIDERS secret', { error: e.message });
  }
}

async function fetchApiUser(domain, cookieName, cookieValue, tabId) {
  // Resolve api_user (numeric ID) for a new-api site.
  // Strategy: read from localStorage first (no network, no cookie interference),
  // then fall back to API call if localStorage is unavailable.

  // Helper: extract user id from new-api localStorage
  function _readLocalStorageUser() {
    // new-api frontend stores user JSON under key "user"
    try {
      const raw = localStorage.getItem('user');
      if (raw) {
        const u = JSON.parse(raw);
        const id = u?.id ?? null;
        if (id != null) return String(id);
      }
    } catch {}
    return null;
  }

  // Helper: call /api/user/self via sync XHR (same-origin, cookies auto-sent)
  function _fetchSelfXHR() {
    try {
      const xhr = new XMLHttpRequest();
      xhr.open('GET', '/api/user/self', false);
      xhr.withCredentials = true;
      xhr.send();
      if (xhr.status === 200) {
        const data = JSON.parse(xhr.responseText);
        return String(data?.data?.id ?? data?.id ?? '');
      }
    } catch {}
    return null;
  }

  // Method 1: Read localStorage in an existing tab (fastest, no network)
  if (tabId) {
    try {
      const results = await chrome.scripting.executeScript({
        target: { tabId },
        func: _readLocalStorageUser,
      });
      const id = results?.[0]?.result;
      if (id) return id;
    } catch {}
  }

  // Method 2: Open temp tab → read localStorage (no API call needed)
  if (!tabId) {
    let tempTab = null;
    try {
      tempTab = await openBackgroundTab(domain);
      // Read localStorage
      const results = await chrome.scripting.executeScript({
        target: { tabId: tempTab.id },
        func: _readLocalStorageUser,
      });
      const id = results?.[0]?.result;
      if (id) {
        await closeTab(tempTab);
        return id;
      }
      // Fallback: try API call in same tab context
      const apiResults = await chrome.scripting.executeScript({
        target: { tabId: tempTab.id },
        func: _fetchSelfXHR,
      });
      const apiId = apiResults?.[0]?.result;
      await closeTab(tempTab);
      if (apiId) return apiId;
    } catch {
      if (tempTab) await closeTab(tempTab);
    }
  }

  // Method 3: Try API call in existing tab context
  if (tabId) {
    try {
      const results = await chrome.scripting.executeScript({
        target: { tabId },
        func: _fetchSelfXHR,
      });
      const id = results?.[0]?.result;
      if (id) return id;
    } catch {}
  }

  return null;
}

// Reverse map: domain → provider name, for auto-generating env_key_suffix (known sites)
const DOMAIN_TO_PROVIDER = {
  'https://anyrouter.top':       'ANYROUTER',
  'https://agentrouter.org':     'AGENTROUTER',
  'https://api.freestyle.cc.cd': 'FREESTYLE',
  'https://ai.xingyungept.cn':   'XINGYUNGEPT',
  'https://newapi.sorai.me':     'SORAI',
  'https://welfare.apikey.cc':   'APIKEY',
  'https://computetoken.ai':     'COMPUTETOKEN',
  'https://cdk.hybgzs.com':     'HEIBAI',
};

// Derive a provider tag for any domain (known or unknown)
function getProviderTag(domain) {
  const normalized = domain.replace(/\/$/, '');
  if (DOMAIN_TO_PROVIDER[normalized]) return DOMAIN_TO_PROVIDER[normalized];
  const hostname = new URL(normalized).hostname;
  const parts = hostname.split('.');
  const skipPrefixes = new Set(['www', 'api', 'app', 'new', 'newapi', 'welfare']);
  const meaningful = parts.find(p => !skipPrefixes.has(p)) || parts[0];
  return meaningful.toUpperCase();
}

function getProviderName(domain) {
  return getProviderTag(domain).toLowerCase();
}

// Known built-in providers (already hardcoded in checkin.py — excluded from PROVIDERS secret)
const BUILTIN_PROVIDERS = new Set(['anyrouter', 'agentrouter', 'heibai']);

// ── Heibai multi-cookie provider ─────────────────────────────────────────────

const HEIBAI_COOKIE_NAMES = [
  'server_name_session',
  '__Host-authjs.csrf-token',
  '__Secure-authjs.callback-url',
  '__Secure-nw-uid',
  '__Secure-authjs.session-token',
];

function isHeibaiProvider(domain) {
  return getProviderName(domain) === 'heibai';
}

async function fetchHeibaiUser(domain, cookies, tabId) {
  // Strategy 1: use __Secure-nw-uid cookie value as user ID
  if (cookies['__Secure-nw-uid']) return cookies['__Secure-nw-uid'];

  // Strategy 2: call /api/auth/session in tab context
  function _fetchAuthSession() {
    try {
      const xhr = new XMLHttpRequest();
      xhr.open('GET', '/api/auth/session', false);
      xhr.withCredentials = true;
      xhr.send();
      if (xhr.status === 200) {
        const data = JSON.parse(xhr.responseText);
        return data?.user?.name || data?.user?.id || null;
      }
    } catch {}
    return null;
  }

  if (tabId) {
    try {
      const results = await chrome.scripting.executeScript({
        target: { tabId },
        func: _fetchAuthSession,
      });
      const id = results?.[0]?.result;
      if (id) return String(id);
    } catch {}
  }

  return null;
}

async function syncHeibaiAccount(config, account, url, hostname) {
  const label = account.env_key_suffix || account.domain;
  let tab = null;

  try {
    // Phase 1: Extract all required cookies directly from cookie jar
    const collectedCookies = {};
    const missingCookies = [];

    for (const name of HEIBAI_COOKIE_NAMES) {
      const cookie = await findCookieAcrossStores(url, hostname, name);
      if (cookie) {
        collectedCookies[name] = cookie.value;
      } else {
        missingCookies.push(name);
      }
    }

    // Phase 2: If any cookies missing, open background tab and retry
    if (missingCookies.length > 0) {
      await Logger.info(`Heibai: ${missingCookies.length} cookies missing, opening tab...`, { missing: missingCookies });
      tab = await openBackgroundTab(url);

      for (const name of missingCookies) {
        const cookie = await findCookieAcrossStores(url, hostname, name);
        if (cookie) {
          collectedCookies[name] = cookie.value;
        }
      }
    }

    // Must have the session token at minimum
    if (!collectedCookies['__Secure-authjs.session-token']) {
      await Logger.error(`Heibai: essential cookie __Secure-authjs.session-token not found for ${label}`, {
        found: Object.keys(collectedCookies),
        hint: '请先在浏览器中登录 cdk.hybgzs.com',
      });
      if (tab) await closeTab(tab);
      return { success: false, label, error: 'session cookie not found — please login to cdk.hybgzs.com' };
    }

    const foundCount = Object.keys(collectedCookies).length;
    await Logger.success(`Heibai: extracted ${foundCount}/${HEIBAI_COOKIE_NAMES.length} cookies for ${label}`);

    // Resolve user identity
    const userId = await fetchHeibaiUser(url, collectedCookies, tab?.id);
    if (tab) { await closeTab(tab); tab = null; }

    if (!userId) {
      await Logger.error(`Heibai: cannot resolve user identity for ${label}`);
      return { success: false, label, error: 'cannot resolve heibai user identity' };
    }
    await Logger.success(`Heibai: resolved user: ${userId}`);

    // Determine secret name
    let { env_key_suffix } = account;
    if (!env_key_suffix) {
      const sanitized = userId.replace(/[^a-zA-Z0-9_]/g, '_').substring(0, 30);
      env_key_suffix = `${sanitized}_HEIBAI`;
      await Logger.info(`Heibai: auto-generated env_key_suffix: ${env_key_suffix}`);
    }

    const secretName = `ANYROUTER_ACCOUNT_${env_key_suffix}`;
    const secretValue = JSON.stringify({
      cookies: collectedCookies,
      provider: 'heibai',
      name: `heibai-${userId}`,
      domain: url,
    });

    await Logger.info(`Pushing to GitHub secret: ${secretName}`);
    await pushToGitHubSecret(config, secretName, secretValue);
    await Logger.success(`✅ ${label}: ${secretName} updated`);
    return { success: true, label, secretName };
  } catch (e) {
    if (tab) await closeTab(tab);
    await Logger.error(`Heibai sync failed for ${label}`, { error: e.message });
    return { success: false, label, error: e.message };
  }
}

// ── Permission check ─────────────────────────────────────────────────────────

async function checkHostPermission(url) {
  try {
    const granted = await chrome.permissions.contains({
      origins: [new URL(url).origin + '/*']
    });
    return granted;
  } catch {
    return false;
  }
}

// ── Cookie store helpers ─────────────────────────────────────────────────────

async function getCookieStoreIds() {
  try {
    const stores = await chrome.cookies.getAllCookieStores();
    return stores.map(s => s.id);
  } catch {
    return ['0'];
  }
}

async function findCookieAcrossStores(url, hostname, cookieName) {
  // Strategy 0: use chrome.cookies.get (exact match — most reliable)
  try {
    const cookie = await chrome.cookies.get({ url, name: cookieName });
    if (cookie) return cookie;
  } catch {}

  // Strategy 1: query by full URL without storeId (let Chrome resolve the store)
  try {
    const cookies = await chrome.cookies.getAll({ url, name: cookieName });
    if (cookies.length > 0) return cookies[0];
  } catch {}

  // Strategy 1b: try with trailing slash (some servers set cookie path to '/')
  try {
    const urlWithSlash = url.endsWith('/') ? url : url + '/';
    const cookies = await chrome.cookies.getAll({ url: urlWithSlash, name: cookieName });
    if (cookies.length > 0) return cookies[0];
  } catch {}

  // Strategy 2: query by domain variants without storeId
  for (const domainQuery of [hostname, `.${hostname}`]) {
    try {
      const cookies = await chrome.cookies.getAll({ domain: domainQuery, name: cookieName });
      if (cookies.length > 0) return cookies[0];
    } catch {}
  }

  // Strategy 3: brute-force — get ALL cookies with this name across entire cookie jar
  try {
    const cookies = await chrome.cookies.getAll({ name: cookieName });
    const match = cookies.find(c =>
      c.domain === hostname || c.domain === `.${hostname}` ||
      hostname.endsWith(c.domain.replace(/^\./, ''))
    );
    if (match) return match;
  } catch {}

  // Strategy 4: enumerate all stores explicitly
  const storeIds = await getCookieStoreIds();
  for (const storeId of storeIds) {
    try {
      const cookies = await chrome.cookies.getAll({ url, name: cookieName, storeId });
      if (cookies.length > 0) return cookies[0];
    } catch {}
    for (const domainQuery of [hostname, `.${hostname}`]) {
      try {
        const cookies = await chrome.cookies.getAll({ domain: domainQuery, name: cookieName, storeId });
        if (cookies.length > 0) return cookies[0];
      } catch {}
    }
  }

  // Strategy 5: get ALL cookies for this domain (any name) — debug what's there
  try {
    const allForUrl = await chrome.cookies.getAll({ url });
    const allForDomain = await chrome.cookies.getAll({ domain: hostname });
    const allForDotDomain = await chrome.cookies.getAll({ domain: `.${hostname}` });
    const combined = [...allForUrl, ...allForDomain, ...allForDotDomain];
    if (combined.length > 0) {
      await Logger.info(`findCookieAcrossStores debug: found ${combined.length} cookies for ${hostname} but none named "${cookieName}"`, {
        cookie_names: [...new Set(combined.map(c => c.name))],
        details: combined.slice(0, 10).map(c => ({ name: c.name, domain: c.domain, httpOnly: c.httpOnly, secure: c.secure })),
      });
    }
  } catch {}

  return null;
}

async function getAllCookiesForDomain(url, hostname) {
  const all = [];

  // Without storeId
  try {
    const cookies = await chrome.cookies.getAll({ url });
    all.push(...cookies);
  } catch {}
  for (const domainQuery of [hostname, `.${hostname}`]) {
    try {
      const cookies = await chrome.cookies.getAll({ domain: domainQuery });
      all.push(...cookies);
    } catch {}
  }

  // With explicit storeIds
  const storeIds = await getCookieStoreIds();
  for (const storeId of storeIds) {
    try {
      const cookies = await chrome.cookies.getAll({ url, storeId });
      all.push(...cookies);
    } catch {}
    for (const domainQuery of [hostname, `.${hostname}`]) {
      try {
        const cookies = await chrome.cookies.getAll({ domain: domainQuery, storeId });
        all.push(...cookies);
      } catch {}
    }
  }

  // Deduplicate by name+domain
  const seen = new Set();
  return all.filter(c => {
    const key = c.name + '|' + c.domain;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

// ── Tab helpers ──────────────────────────────────────────────────────────────

async function openBackgroundTab(url) {
  // Set up the listener BEFORE creating the tab to avoid race condition
  let resolveLoad;
  const loadPromise = new Promise(resolve => { resolveLoad = resolve; });

  // We'll capture the tab ID once we have it
  let targetTabId = null;

  const listener = (tabId, changeInfo) => {
    if (targetTabId !== null && tabId === targetTabId) {
      // Re-inject auth capture hook on each navigation (handles OAuth redirects)
      if (changeInfo.status === 'loading') {
        injectAuthCaptureHook(tabId);
      }
      if (changeInfo.status === 'complete') {
        chrome.tabs.onUpdated.removeListener(listener);
        resolveLoad();
      }
    }
  };
  chrome.tabs.onUpdated.addListener(listener);

  const tab = await chrome.tabs.create({ url, active: false });
  targetTabId = tab.id;

  // Inject auth capture hook immediately
  await injectAuthCaptureHook(tab.id);

  // Check if tab already completed loading before we set targetTabId
  try {
    const currentTab = await chrome.tabs.get(tab.id);
    if (currentTab.status === 'complete') {
      chrome.tabs.onUpdated.removeListener(listener);
      resolveLoad();
    }
  } catch {}

  // Safety timeout
  const timeout = setTimeout(() => {
    chrome.tabs.onUpdated.removeListener(listener);
    resolveLoad();
  }, 15000);

  await loadPromise;
  clearTimeout(timeout);

  // Wait for JS-set cookies
  await new Promise(r => setTimeout(r, 3000));
  return tab;
}

async function closeTab(tab) {
  try { await chrome.tabs.remove(tab.id); } catch {}
}

// ── Content script injection ─────────────────────────────────────────────────

async function readPageInfoViaScripting(tabId) {
  // Use chrome.scripting.executeScript to read info directly from the page
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId },
      func: () => ({
        url: location.href,
        documentCookie: document.cookie,
        cookieNames: document.cookie.split('; ').filter(Boolean).map(c => c.split('=')[0]),
        title: document.title,
        readyState: document.readyState,
        // Detect login page: check for login form, password inputs, or login-related URL paths
        isLoginPage: !!(
          document.querySelector('input[type="password"]') ||
          /\/(login|signin|sign-in|register|auth)\b/i.test(location.pathname)
        ),
        // Check localStorage for cached user data (session might be expired)
        hasLocalStorageUser: !!(localStorage.getItem('user')),
      }),
    });
    return results?.[0]?.result || null;
  } catch (e) {
    await Logger.error('chrome.scripting.executeScript failed', { error: e.message, tabId });
    return null;
  }
}

// ── MAIN world auth token capture ────────────────────────────────────────────

async function injectAuthCaptureHook(tabId) {
  // Inject a script in the MAIN world to intercept Authorization headers
  // from the page's fetch/XHR calls (for sites using token-based auth)
  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      world: 'MAIN',
      injectImmediately: true,
      func: () => {
        if (window.__authCaptureInstalled) return;
        window.__authCaptureInstalled = true;
        window.__capturedAuthToken = null;
        window.__capturedSignInData = null;

        // Hook fetch
        const origFetch = window.fetch;
        window.fetch = function(...args) {
          const [input, init] = args;
          const url = typeof input === 'string' ? input : (input?.url || '');
          if (init?.headers) {
            const h = init.headers;
            const auth = h instanceof Headers ? h.get('Authorization')
              : (h.Authorization || h.authorization || null);
            if (auth) window.__capturedAuthToken = auth;
          }
          // Intercept sign_in response to capture session token
          const result = origFetch.apply(this, args);
          if (url.includes('/api/user/login') || url.includes('/api/user/sign_in') || url.includes('/api/oauth/')) {
            result.then(r => r.clone().json()).then(data => {
              window.__capturedSignInData = data;
            }).catch(() => {});
          }
          return result;
        };

        // Hook XHR
        const origSetHeader = XMLHttpRequest.prototype.setRequestHeader;
        XMLHttpRequest.prototype.setRequestHeader = function(name, value) {
          if (name.toLowerCase() === 'authorization') window.__capturedAuthToken = value;
          return origSetHeader.call(this, name, value);
        };
      },
    });
  } catch {
    // MAIN world injection may fail on some pages (e.g., chrome:// URLs)
  }
}

async function readCapturedAuth(tabId) {
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId },
      world: 'MAIN',
      func: () => ({
        authToken: window.__capturedAuthToken || null,
        signInData: window.__capturedSignInData || null,
      }),
    });
    return results?.[0]?.result || null;
  } catch {
    return null;
  }
}

// ── Diagnostic helper ────────────────────────────────────────────────────────

async function diagnoseCookieAccess(url, hostname) {
  // Try to get ANY cookies to test basic access
  let totalCookies = 0;
  let domainSample = [];
  try {
    const all = await chrome.cookies.getAll({});
    totalCookies = all.length;
    // Collect unique domains to help debug
    const domains = new Set(all.map(c => c.domain));
    // Show domains that look related to the target
    const related = [...domains].filter(d =>
      d.includes(hostname) || hostname.includes(d.replace(/^\./, ''))
    );
    // Also show a sample of all domains
    domainSample = [...domains].slice(0, 30);
    if (related.length > 0) {
      await Logger.info(`Found related cookie domains for ${hostname}`, { related });
    }
  } catch (e) {
    await Logger.error('chrome.cookies.getAll({}) failed — cookies API may be broken', { error: e.message });
    return;
  }

  // Check host permission
  const hasPermission = await checkHostPermission(url);

  await Logger.error(`Cookie diagnostic for ${hostname}`, {
    total_cookies_in_browser: totalCookies,
    host_permission_granted: hasPermission,
    stores: await getCookieStoreIds(),
    cookie_domains_sample: domainSample,
    hint: !hasPermission
      ? '扩展没有该站点的 host 权限。请右键扩展图标 → "此扩展可以读取和更改网站数据" → 选择"在所有网站上"'
      : totalCookies === 0
        ? '浏览器中没有任何 cookie，请确认已登录目标网站'
        : '浏览器有 cookie 但目标域名无 cookie，请确认已登录该网站',
  });
}

// ─────────────────────────────────────────────────────────────────────────────

async function syncOneAccount(config, account, options = {}) {
  const { domain, cookie_name } = account;
  const { dryRun = false } = options;
  let { api_user, env_key_suffix } = account;
  const targetCookieName = cookie_name || 'session';
  const label = env_key_suffix || domain;
  let tab = null;

  try {
    const url = domain.replace(/\/$/, '');
    const hostname = new URL(url).hostname;

    // Check host permission first
    const hasPermission = await checkHostPermission(url);
    if (!hasPermission) {
      await Logger.error(`No host permission for ${label}. 请右键扩展图标 → "此扩展可以读取和更改网站数据" → "在所有网站上"`, { domain });
      return { success: false, label, error: 'no host permission' };
    }

    // ── Special handling: heibai multi-cookie provider ──
    if (isHeibaiProvider(domain)) {
      return await syncHeibaiAccount(config, account, url, hostname);
    }

    // ── Phase 1: Try to read cookie DIRECTLY from the cookie jar (no tab needed) ──
    // Opening a background tab can interfere with session cookies (server may
    // invalidate/rotate the session when it sees a second concurrent request).
    let cookie = await findCookieAcrossStores(url, hostname, targetCookieName);

    if (cookie) {
      await Logger.info(`Cookie "${targetCookieName}" found directly from cookie jar for ${label}`, {
        domain: cookie.domain,
        length: cookie.value.length,
        httpOnly: cookie.httpOnly,
        secure: cookie.secure,
      });
    }

    // ── Phase 2: If not found, open background tab to populate cookies ──
    let pageInfo = null;
    if (!cookie) {
      await Logger.info(`Cookie not in jar, opening ${url} in background tab to extract cookie "${targetCookieName}"...`, { domain });
      tab = await openBackgroundTab(url);

      // Read page info via content script injection
      pageInfo = await readPageInfoViaScripting(tab.id);
      if (pageInfo) {
        await Logger.info(`Page loaded for ${label}`, {
          actual_url: pageInfo.url,
          page_title: pageInfo.title,
          document_cookie_names: pageInfo.cookieNames,
          ready_state: pageInfo.readyState,
        });
      }

      // Retry cookie lookup after page load
      cookie = await findCookieAcrossStores(url, hostname, targetCookieName);

      // Try document.cookie as fallback (non-httpOnly cookies)
      if (!cookie && pageInfo?.documentCookie) {
        const match = pageInfo.documentCookie.split('; ').find(c => c.startsWith(targetCookieName + '='));
        if (match) {
          const val = match.split('=').slice(1).join('=');
          await Logger.info(`Cookie "${targetCookieName}" found via document.cookie (not in cookies API)`, { length: val.length });
          cookie = { value: val, name: targetCookieName, domain: hostname };
        }
      }

      // Try captured auth token from page's JS context (token-based auth fallback)
      if (!cookie) {
        const capturedAuth = await readCapturedAuth(tab.id);
        if (capturedAuth?.authToken) {
          const tokenValue = capturedAuth.authToken.replace(/^Bearer\s+/i, '');
          await Logger.info(`No cookie but captured auth token for ${label}`, { tokenLength: tokenValue.length });
          cookie = { value: tokenValue, name: targetCookieName, domain: hostname };
        }
      }
    }

    if (!cookie) {
      const allCookies = await getAllCookiesForDomain(url, hostname);

      // Detect WHY the cookie is missing: expired session vs never logged in
      const isLoginPage = pageInfo?.isLoginPage || false;
      const hasStaleCache = pageInfo?.hasLocalStorageUser || false;

      let hint;
      if (isLoginPage) {
        hint = `⚠️ 页面是登录页 — 请先在浏览器中手动登录 ${hostname}，然后重新同步`;
      } else if (hasStaleCache && allCookies.length === 0) {
        hint = `⚠️ Session 已过期（localStorage 有缓存但无有效 cookie）— 请重新登录 ${hostname}`;
      } else if (allCookies.length === 0) {
        hint = `⚠️ 该站点无任何 cookie — 请确认已在浏览器中登录 ${hostname}`;
      } else {
        hint = `⚠️ 有其他 cookie 但找不到 "${targetCookieName}" — 可能站点使用了不同的 cookie 名称`;
      }

      await Logger.error(`Cookie "${targetCookieName}" not found for ${label}`, {
        domain,
        hint,
        actual_page_url: pageInfo?.url || 'unknown',
        page_title: pageInfo?.title || 'unknown',
        is_login_page: isLoginPage,
        session_expired: hasStaleCache && allCookies.length === 0,
        document_cookie_names: pageInfo?.cookieNames || [],
        available_via_api: allCookies.map(c => `${c.name} (domain=${c.domain})`),
        stores_checked: await getCookieStoreIds(),
      });

      // Run diagnostics if zero cookies found
      if (allCookies.length === 0) {
        await diagnoseCookieAccess(url, hostname);
      }

      if (tab) await closeTab(tab);
      return { success: false, label, error: isLoginPage ? 'session expired — please login' : `cookie "${targetCookieName}" not found` };
    }

    const cookieValue = cookie.value;
    await Logger.success(`Cookie extracted for ${label}`, { length: cookieValue.length });

    if (!api_user) {
      await Logger.info(`Fetching api_user from /api/user/self for ${label}...`);
      api_user = await fetchApiUser(domain, targetCookieName, cookieValue, tab?.id);
    }

    // Close the background tab after fetchApiUser is done (it may need the tab)
    if (tab) { await closeTab(tab); tab = null; }
    if (api_user) {
      await Logger.success(`Resolved api_user: ${api_user}`);
    } else {
      await Logger.error(`Could not resolve api_user for ${label}`);
    }

    // Determine secret suffix
    const providerTag = getProviderTag(domain);
    const providerName = providerTag.toLowerCase();

    if (dryRun) {
      await Logger.success(`Test passed for ${label}`, {
        cookie_name: targetCookieName,
        api_user: api_user || null,
        provider: providerName,
      });
      return {
        success: true,
        label,
        api_user,
        provider: providerName,
        cookieName: targetCookieName,
      };
    }

    if (!env_key_suffix) {
      if (!api_user) {
        await Logger.error(`Cannot determine secret name for ${label}: no env_key_suffix and api_user unavailable`);
        return { success: false, label, error: 'cannot determine secret name (no env_key_suffix, api_user unavailable)' };
      }
      env_key_suffix = `${api_user}_${providerTag}`;
      await Logger.info(`Auto-generated env_key_suffix: ${env_key_suffix}`);
    }

    if (!api_user) {
      await Logger.error(`Skipping ${label}: api_user unavailable, refusing to push incomplete secret`);
      return { success: false, label, error: 'api_user unavailable' };
    }

    const secretName = `ANYROUTER_ACCOUNT_${env_key_suffix}`;
    const secretValue = JSON.stringify({
      cookies: { [targetCookieName]: cookieValue },
      api_user,
      provider: providerName,
      domain: domain.replace(/\/$/, ''),
    });

    await Logger.info(`Pushing to GitHub secret: ${secretName}`);
    await pushToGitHubSecret(config, secretName, secretValue);
    await Logger.success(`✅ ${label}: ${secretName} updated`);
    return { success: true, label, secretName };
  } catch (e) {
    if (tab) await closeTab(tab);
    await Logger.error(`Failed for ${label}`, { error: e.message });
    return { success: false, label, error: e.message };
  }
}

// --- GitHub Secrets Encryption (libsodium crypto_box_seal) ---

let _cachedRepoId = null;
async function getRepoId(config) {
  if (_cachedRepoId) return _cachedRepoId;
  const { githubToken, repoOwner, repoName } = config;
  const resp = await fetch(`https://api.github.com/repos/${repoOwner}/${repoName}`, {
    headers: { Authorization: `Bearer ${githubToken}`, Accept: 'application/vnd.github+json' }
  });
  if (!resp.ok) throw new Error(`Failed to get repo: ${resp.status}`);
  _cachedRepoId = (await resp.json()).id;
  return _cachedRepoId;
}

async function getPublicKey(config) {
  const { githubToken, repoOwner, repoName, environmentName } = config;
  let url;
  if (environmentName) {
    const repoId = await getRepoId(config);
    url = `https://api.github.com/repositories/${repoId}/environments/${encodeURIComponent(environmentName)}/secrets/public-key`;
  } else {
    url = `https://api.github.com/repos/${repoOwner}/${repoName}/actions/secrets/public-key`;
  }
  const resp = await fetch(url, {
    headers: { Authorization: `Bearer ${githubToken}`, Accept: 'application/vnd.github+json' }
  });
  if (!resp.ok) throw new Error(`Failed to get public key: ${resp.status} ${await resp.text()}`);
  return resp.json();
}

async function pushToGitHubSecret(config, secretName, secretValue) {
  await sodium.ready;

  const { githubToken, repoOwner, repoName, environmentName } = config;
  const { key, key_id } = await getPublicKey(config);

  const publicKeyBytes = sodium.from_base64(key, sodium.base64_variants.ORIGINAL);
  const messageBytes = sodium.from_string(secretValue);
  const encryptedBytes = sodium.crypto_box_seal(messageBytes, publicKeyBytes);
  const encryptedValue = sodium.to_base64(encryptedBytes, sodium.base64_variants.ORIGINAL);

  let url;
  if (environmentName) {
    const repoId = await getRepoId(config);
    url = `https://api.github.com/repositories/${repoId}/environments/${encodeURIComponent(environmentName)}/secrets/${secretName}`;
  } else {
    url = `https://api.github.com/repos/${repoOwner}/${repoName}/actions/secrets/${secretName}`;
  }

  const resp = await fetch(url, {
    method: 'PUT',
    headers: {
      Authorization: `Bearer ${githubToken}`,
      Accept: 'application/vnd.github+json',
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ encrypted_value: encryptedValue, key_id })
  });

  if (!resp.ok) throw new Error(`GitHub API ${resp.status}: ${await resp.text()}`);
}
