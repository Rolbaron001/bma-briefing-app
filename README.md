# BMA Daily Brief - Intelligence Centre (desktop app)

A local desktop dashboard that gives the DAC a daily open-source border-threat
brief across the four BMA clusters, lets him pin and track items over time, and
generate Risk and Threat Assessments on demand.

It runs entirely on the user's own PC. Nothing is sent anywhere except the
outbound news requests it makes to fetch current reporting.

## What is in this folder

- **Start BMA Daily Brief.bat** - double-click this to run the app.
- **server.py** - the small local program that serves the dashboard and pulls the news.
- **index.html** - the dashboard itself (opens automatically in your browser).
- **README.md** - this guide.

## One-time setup

1. Install Python (only needed once per PC). Download it from
   https://www.python.org/downloads/ and during setup **tick "Add python.exe to PATH"**.
   No other downloads or packages are required.

## Running it

1. Double-click **Start BMA Daily Brief.bat**.
2. A small black window opens (that is the app engine) and your browser opens the
   dashboard automatically at http://localhost:8770.
3. Leave the black window open while you use the app. To stop, close that window.

## Optional: put a shortcut on the Desktop

To launch the app without opening this folder each time:

1. Double-click **Create Desktop Shortcut.bat** (run it once).
2. A **BMA Daily Brief** shortcut with the BMA icon appears on the Desktop.
3. From then on, just double-click that shortcut to open the dashboard.

## Using the dashboard

- **Daily brief** - four cluster panels (A People Movement, B Illicit Goods,
  C Coastal and Maritime, D Cross-Cutting Enablers). Each panel scrolls
  independently. Click **Refresh now** to pull the latest open-source reporting.
- **Pin** any item to move it to the **Watchlist**, where you can add dated
  tracking notes and follow it over time.
- When an item is no longer current, click **Close and archive**. Archived items
  are kept and can be exported to a file for off-line storage.
- **Request a Risk / Threat Assessment** - type a question or use a preset
  (for example threats against Cape Town International Airport, illegal crossing
  from Zimbabwe, or the modus operandi of narcotics syndicates into Gauteng),
  pick a product type, and generate it on screen. **Copy for full .docx** hands
  the request to Claude to produce a BMA-branded Word document.

## Optional: on-screen AI assessments

The dashboard works without any AI. If you want the assessments written on screen
automatically, add an Anthropic API key:

1. Create a plain text file named **apikey.txt** in this folder.
2. Paste your Anthropic API key as the only line and save.
3. Restart the app. The header will show that AI assessments are enabled.

Without a key, assessments produce a structured scaffold you can complete, plus
the **Copy for full .docx** hand-off to Claude.

## If a refresh comes back empty

That usually means the PC could not reach the news service at that moment
(no internet, or a corporate firewall blocking it). The last brief stays on
screen. Try **Refresh now** again, or check the connection.

## Notes

- The brief is open-source only. Nothing here implies classified access. Verify
  every item against its original source before using it in a formal product.
- Motto: Secure Borders for Development - www.bma.gov.za
