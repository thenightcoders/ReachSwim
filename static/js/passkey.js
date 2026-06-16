/**
 * passkey.js — WebAuthn registration and authentication flows.
 *
 * No dependencies. Two entry points:
 *   - #passkey-auth-btn  (login page)
 *   - #add-passkey-btn   (profile page)
 *
 * The WebAuthn API works with ArrayBuffers. The server (py_webauthn) sends
 * and expects base64url strings, so we convert in both directions here.
 */

// ---------------------------------------------------------------------------
// base64url ↔ ArrayBuffer helpers
// ---------------------------------------------------------------------------

function bufToBase64url(buf) {
  return btoa(String.fromCharCode(...new Uint8Array(buf)))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
}

function base64urlToBuf(str) {
  // Re-pad, convert to standard base64, decode
  const padded = str.replace(/-/g, '+').replace(/_/g, '/');
  const binary = atob(padded);
  return Uint8Array.from(binary, c => c.charCodeAt(0)).buffer;
}

// ---------------------------------------------------------------------------
// Transform server options into WebAuthn API format
// py_webauthn serialises options with base64url strings; the browser wants
// ArrayBuffers for challenge, user.id, and credential IDs.
// ---------------------------------------------------------------------------

function prepareRegistrationOptions(opts) {
  opts.challenge = base64urlToBuf(opts.challenge);
  opts.user.id   = base64urlToBuf(opts.user.id);
  if (opts.excludeCredentials) {
    opts.excludeCredentials = opts.excludeCredentials.map(c => ({
      ...c, id: base64urlToBuf(c.id),
    }));
  }
  return opts;
}

function prepareAuthenticationOptions(opts) {
  opts.challenge = base64urlToBuf(opts.challenge);
  if (opts.allowCredentials) {
    opts.allowCredentials = opts.allowCredentials.map(c => ({
      ...c, id: base64urlToBuf(c.id),
    }));
  }
  return opts;
}

// ---------------------------------------------------------------------------
// Serialize a PublicKeyCredential back to JSON for the server.
// All ArrayBuffer fields → base64url strings.
// ---------------------------------------------------------------------------

function credentialToJSON(cred) {
  const resp = cred.response;
  const obj = {
    id:    cred.id,
    rawId: bufToBase64url(cred.rawId),
    type:  cred.type,
    response: {
      clientDataJSON: bufToBase64url(resp.clientDataJSON),
    },
  };

  // Registration (attestation)
  if (resp.attestationObject) {
    obj.response.attestationObject = bufToBase64url(resp.attestationObject);
  }

  // Authentication (assertion)
  if (resp.authenticatorData) {
    obj.response.authenticatorData = bufToBase64url(resp.authenticatorData);
  }
  if (resp.signature) {
    obj.response.signature = bufToBase64url(resp.signature);
  }
  if (resp.userHandle) {
    obj.response.userHandle = bufToBase64url(resp.userHandle);
  }

  return obj;
}

// ---------------------------------------------------------------------------
// Shared fetch helper — JSON in, JSON out, CSRF header attached
// ---------------------------------------------------------------------------

async function postJSON(url, csrf, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': csrf,
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  return res.json();
}

// ---------------------------------------------------------------------------
// Authentication flow (login page → #passkey-auth-btn)
// ---------------------------------------------------------------------------

async function passkeyAuth(btn) {
  const challengeUrl = btn.dataset.challengeUrl;
  const completeUrl  = btn.dataset.completeUrl;
  const csrf         = btn.dataset.csrf;
  const errEl        = document.getElementById('passkey-error');

  function showErr(msg) {
    if (errEl) { errEl.textContent = msg; errEl.style.display = ''; }
    btn.disabled = false;
    btn.textContent = 'Use passkey';
  }

  btn.disabled = true;
  btn.textContent = 'Waiting for authenticator…';
  if (errEl) errEl.style.display = 'none';

  try {
    // 1. Get challenge from server
    const optionsRaw = await postJSON(challengeUrl, csrf);
    if (optionsRaw.error) { showErr(optionsRaw.error); return; }

    // 2. Ask browser / OS to authenticate
    const publicKey = prepareAuthenticationOptions(optionsRaw);
    let credential;
    try {
      credential = await navigator.credentials.get({ publicKey });
    } catch (e) {
      if (e.name === 'NotAllowedError') {
        showErr('Authentication cancelled.');
      } else {
        showErr('Passkey authentication failed. Make sure you have a passkey registered.');
      }
      return;
    }

    // 3. Send assertion to server
    btn.textContent = 'Verifying…';
    const result = await postJSON(completeUrl, csrf, credentialToJSON(credential));

    if (result.success) {
      window.location.href = result.redirect;
    } else {
      showErr(result.error || 'Authentication failed. Try another method.');
    }
  } catch (e) {
    showErr('Unexpected error. Please try again.');
    console.error('[passkey auth]', e);
  }
}

// ---------------------------------------------------------------------------
// Registration flow (profile page → #add-passkey-btn)
// ---------------------------------------------------------------------------

async function passkeyRegister(btn) {
  const challengeUrl = btn.dataset.challengeUrl;
  const completeUrl  = btn.dataset.completeUrl;
  const csrf         = btn.dataset.csrf;
  const statusEl     = document.getElementById('passkey-reg-status');

  function setStatus(msg, isError) {
    if (!statusEl) return;
    statusEl.style.display = '';
    statusEl.style.color   = isError ? '#b02020' : 'inherit';
    statusEl.textContent   = msg;
  }

  btn.disabled = true;
  if (statusEl) statusEl.style.display = 'none';

  // Prompt for a friendly name
  const name = prompt('Name this passkey (e.g. "iPhone 15", "YubiKey"):', 'My passkey');
  if (name === null) { btn.disabled = false; return; } // cancelled

  try {
    // 1. Get registration options from server
    const optsRaw = await postJSON(challengeUrl, csrf);
    if (optsRaw.error) { setStatus(optsRaw.error, true); btn.disabled = false; return; }

    // 2. Ask browser / OS to create the credential
    const publicKey = prepareRegistrationOptions(optsRaw);
    let credential;
    try {
      credential = await navigator.credentials.create({ publicKey });
    } catch (e) {
      if (e.name === 'NotAllowedError') {
        setStatus('Registration cancelled.', true);
      } else {
        setStatus('Could not create passkey: ' + e.message, true);
      }
      btn.disabled = false;
      return;
    }

    // 3. Send attestation to server, including the user-supplied name
    const payload = { ...credentialToJSON(credential), name: name.trim() || 'Passkey' };
    const result  = await postJSON(completeUrl, csrf, payload);

    if (result.success) {
      setStatus('Passkey added! Refreshing…', false);
      setTimeout(() => window.location.reload(), 800);
    } else {
      setStatus(result.error || 'Registration failed.', true);
      btn.disabled = false;
    }
  } catch (e) {
    setStatus('Unexpected error. Please try again.', true);
    console.error('[passkey register]', e);
    btn.disabled = false;
  }
}

// ---------------------------------------------------------------------------
// Wire up on DOM ready
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
  const authBtn = document.getElementById('passkey-auth-btn');
  if (authBtn) {
    authBtn.addEventListener('click', () => passkeyAuth(authBtn));
  }

  const regBtn = document.getElementById('add-passkey-btn');
  if (regBtn) {
    regBtn.addEventListener('click', () => passkeyRegister(regBtn));
  }
});
