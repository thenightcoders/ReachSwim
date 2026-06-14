# Google Calendar Setup Guide

This guide is for the coach (site owner). No technical knowledge required — just follow these steps once and bookings will automatically appear in your Google Calendar.

---

## Part 1 — Google Cloud Console (one-time setup, ~10 minutes)

### 1. Create a project

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Sign in with the Google account whose calendar you want to use
3. Click the project dropdown at the top → **New Project**
4. Name it anything (e.g. "ReachSwim") → **Create**

### 2. Enable the Google Calendar API

1. In the left menu go to **APIs & Services → Library**
2. Search for "Google Calendar API"
3. Click it → **Enable**

### 3. Set up the OAuth consent screen

1. Go to **APIs & Services → OAuth consent screen**
2. Choose **External** → **Create**
3. Fill in:
   - **App name**: ReachSwim (or anything you like)
   - **User support email**: your email address
   - **Developer contact email**: your email address
4. Click **Save and Continue** through the next screens (no need to add scopes manually)
5. On the **Test users** screen, click **Add users** and add your own Gmail address
6. Click **Save and Continue** → **Back to Dashboard**

### 4. Create OAuth credentials

1. Go to **APIs & Services → Credentials**
2. Click **+ Create Credentials → OAuth client ID**
3. Application type: **Web application**
4. Name: anything (e.g. "ReachSwim Web")
5. Under **Authorised redirect URIs**, click **Add URI** and paste:
   ```
   https://your-domain.com/dashboard/google-calendar/callback/
   ```
   *(Replace `your-domain.com` with your actual domain. If testing locally: `http://127.0.0.1:8000/dashboard/google-calendar/callback/`)*
6. Click **Create**
7. A popup shows your **Client ID** and **Client Secret** — copy both and keep them safe

---

## Part 2 — Dashboard Settings

### 5. Enter your credentials

1. Log into your dashboard at `/dashboard/`
2. Go to **Settings** (left sidebar)
3. Click the **Google Calendar** tab
4. Paste your **Client ID** and **Client Secret** into the fields
5. Leave **Calendar ID** as `primary` (this uses your main Google calendar)
6. Click **Save Credentials**

### 6. Connect your calendar

1. Still on the **Google Calendar** tab, click **Connect Google Calendar**
2. You'll be redirected to Google — sign in and click **Allow**
3. You'll be sent back to the dashboard
4. The tab now shows a green **Connected ✓** badge

That's it. From this point:

- Every time a client completes a booking, an event is automatically added to your Google Calendar
- If you add an event to your calendar yourself (a holiday, personal appointment, etc.), that time will be blocked and clients won't be able to book it

---

## Disconnecting

Go to **Settings → Google Calendar** and click **Disconnect**. Your existing calendar events won't be deleted, but new bookings will stop syncing.

---

## Troubleshooting

**"Connect" button is greyed out** — you haven't saved your Client ID and Client Secret yet (Step 5).

**Google shows an error after authorising** — double-check the redirect URI in Google Cloud Console matches exactly what's shown on the settings page (including `http` vs `https`).

**Bookings aren't showing in my calendar** — make sure you're signed into the same Google account you used to set up the project, and that your email is listed as a test user (Step 3, point 5).
