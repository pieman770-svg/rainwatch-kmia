# RainWatch — KMIA (Free)

A zero-cost personal rain monitor for **KMIA / Miami International Airport**.

It checks the NWS KMIA latest observation on a schedule, reads `precipitationLastHour`,
and sends an iPhone push notification through the free ntfy service when the value is
**>= 0.10 inches**.

The dashboard is a static GitHub Pages site, so there is no paid server.

## Architecture

GitHub Actions scheduler → NWS API → threshold check → ntfy iPhone notification
                                      ↘ GitHub Pages dashboard

## Setup

### 1. Create a GitHub repository

Create a **public** GitHub repository (for example `rainwatch-kmia`).
Public repositories get free and unlimited standard GitHub-hosted runner use.

Upload this project's files.

### 2. Create an ntfy topic

Install the official ntfy iPhone app and subscribe to a long, random topic name.

Example:
`rainwatch-kmia-8f3a9d2c7b1e`

Do not use a common/public topic name.

### 3. Add the GitHub secret

Repository → Settings → Secrets and variables → Actions → New repository secret

Name:
`NTFY_TOPIC`

Value:
your random ntfy topic.

### 4. Enable GitHub Pages

Repository → Settings → Pages

Set:
- Source: GitHub Actions

The included workflow deploys `docs/` as the dashboard.

### 5. Run it once

Repository → Actions → `RainWatch KMIA` → Run workflow.

The dashboard will populate after the first successful run.

The scheduled job runs every 15 minutes. GitHub Actions schedules can occasionally
start late, so this is intended as a practical personal alert rather than a
safety-critical alarm.

## iPhone

After GitHub Pages is live:

1. Open the Pages URL in Safari.
2. Use Share → Add to Home Screen.
3. Open the ntfy iPhone app and subscribe to your topic.
4. Leave notifications enabled for ntfy.

The RainWatch dashboard is then available from your iPhone Home Screen, while ntfy
delivers the actual push notification.

## Fixed settings

Station: `KMIA`
Threshold: `0.10 in/hr`
Metric: NWS `precipitationLastHour`

This project intentionally does not monitor other stations or forecasts.
