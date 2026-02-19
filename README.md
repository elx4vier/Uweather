# UWeather – Ulauncher Weather Extension

[![Ulauncher Extension](https://img.shields.io/badge/Ulauncher-Extension-green.svg)](https://ext.ulauncher.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**UWeather** is a fast and lightweight weather extension for [Ulauncher](https://ulauncher.io/).  
It uses the free [Open-Meteo API](https://open-meteo.com/) to provide current weather and a 3‑day forecast.  
The extension supports automatic location detection, manual city selection, and three interface styles.  
Translations are included for multiple languages.

![UWeather Demo](images/uweather.gif)

## ✨ Features

- **Current weather** – temperature and weather condition.
- **3‑day forecast** – tomorrow and day after tomorrow (in *Complete* mode).
- **Automatic location** – detected via IP (ip-api.com / freeipapi.com) – zero configuration.
- **Manual location** – set a fixed city in preferences.
- **City search** – type a city name after the keyword to get weather for that location.
- **Temperature unit** – Celsius or Fahrenheit.
- **Three display modes** – choose how much information you see.
- **Localised descriptions** – translations for:
  - English (en)
  - Portuguese (pt)
  - Spanish (es)
  - French (fr)
  - German (de)
  - Russian (ru)
- **Country flags** – displayed next to the city name (when available).
- **Caching** – weather data is cached for 10 minutes to avoid unnecessary API calls.
- **Click to open** – opens detailed forecast on [weather.com](https://weather.com).

## 📦 Installation

### From the Ulauncher Extensions website (recommended)

1. Open Ulauncher → Preferences → Extensions.
2. Click "Add extension" and paste the following URL:

```
https://github.com/elx4vier/Uweather
```

3. The extension will be installed automatically.

### Manual installation

```bash
# Clone the repository into Ulauncher's user extensions folder
git clone https://github.com/elx4vier/Uweather.git ~/.local/share/ulauncher/extensions/ulauncher-uweather
```

After installation, restart Ulauncher or run `ulauncher-toggle` to reload extensions.

## ⚙️ Configuration

Open Ulauncher Preferences → Extensions → UWeather. You can adjust:

| Preference | Description | Default |
|------------|-------------|---------|
| Keyword | Trigger word for the extension. | w |
| Temperature Unit | °C or °F. | °C |
| Location Mode | Automatic (IP detection) or Manual (fixed city). | auto |
| Static Location | City name for manual mode (e.g., Lisbon, New York). Only used when Location Mode is Manual. | (empty) |
| Interface Display | How weather information is shown – see table below. | essential |

### Interface Display Modes

| Mode | Description |
|------|-------------|
| Complete | Shows location, current weather, and a 3‑day forecast (tomorrow and day after). |
| Essential | Displays current temperature + description on the first line, location on the second line. |
| Minimal | Compact single‑line view: temp – location (description). |

## 🚀 Usage

- **Quick weather** – Just type your keyword (e.g., `w`) and press Enter. The extension shows weather for your current (or manually set) location.
- **Search for a city** – Type the keyword followed by a city name, e.g., `w Paris`. You’ll get up to three matching locations with their current weather.
- **Click on a result** – opens the full forecast on [weather.com](https://weather.com).

## 🌍 Translation

UWeather automatically detects your system language and displays weather descriptions in that language (if a translation is available).  
Translation files are stored in `translations/` and are simple JSON files. To add a new language, copy `en.json`, translate the strings, and save as `[language-code].json` (e.g., `it.json` for Italian). Contributions are welcome!

## 🛠 Development

### Requirements

- Ulauncher 5.0 or later
- Python 3.6 or later
- `requests` and `urllib3` (usually installed by default with Ulauncher)

## 🤝 Contributing

- Report bugs or suggest features via GitHub Issues.
- Pull requests are welcome – please follow the existing code style.
- Translations are especially appreciated!

## 📄 License

This project is licensed under the MIT License – see the LICENSE file for details.

## 🙏 Acknowledgements

- Open-Meteo for the free weather API.
- ip-api.com and freeipapi.com for IP geolocation.
- Ulauncher team for the awesome launcher.
- Weather icons from the [Papirus Icon Theme](https://github.com/PapirusDevelopmentTeam/papirus-icon-theme)

