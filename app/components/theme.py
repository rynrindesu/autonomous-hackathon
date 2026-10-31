"""Theme and CSS for the Triad disruption desk."""

from __future__ import annotations

CSS = r"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap');

:root {
  --td-paper: #f2f0e9;
  --td-paper-2: #eae7de;
  --td-surface: #fbfaf6;
  --td-surface-2: #f6f3ea;
  --td-ink: #132527;
  --td-ink-2: #2b3f42;
  --td-muted: #647275;
  --td-muted-2: #8a9697;
  --td-line: #d9d4c6;
  --td-line-2: #e8e3d7;
  --td-line-strong: #b8b1a1;
  --td-deep: #0f292c;
  --td-deep-2: #173b3e;
  --td-teal: #0d5a56;
  --td-blue: #2b5e80;
  --td-green: #196a4d;
  --td-green-bg: #edf6f0;
  --td-amber: #a26100;
  --td-amber-bg: #fbf3e4;
  --td-red: #a52e2a;
  --td-red-bg: #fbefed;
  --td-violet: #5c4a7c;
  --td-atc: #1d6073;
  --td-pilot: #5c4a7c;
  --td-ground: #8a5a15;
  --td-display: "Barlow Condensed", "Avenir Next Condensed", "Helvetica Neue", sans-serif;
  --td-body: "IBM Plex Sans", "Avenir Next", "Segoe UI", sans-serif;
  --td-mono: "IBM Plex Mono", "SFMono-Regular", Menlo, monospace;
  --td-shadow: 0 1px 0 rgba(19,37,39,.04), 0 12px 34px rgba(19,37,39,.055);
}

html, body, .stApp, [class*="css"] {
  font-family: var(--td-body);
  color: var(--td-ink);
}

.stApp {
  background-color: var(--td-paper);
  background-image: radial-gradient(rgba(19,37,39,.045) .55px, transparent .55px);
  background-size: 9px 9px;
}

[data-testid="stAppViewContainer"] { background: transparent; }
[data-testid="stHeader"] { background: transparent; height: 0; }
[data-testid="stToolbar"] { right: 1rem; }
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }

.block-container {
  max-width: 1560px;
  padding-top: 1.4rem;
  padding-bottom: 3rem;
  padding-left: 2.2rem;
  padding-right: 2.2rem;
}

h1, h2, h3, h4 {
  font-family: var(--td-display) !important;
  font-weight: 600 !important;
  letter-spacing: .02em !important;
  color: var(--td-ink);
}

p, li, span, div { font-family: var(--td-body); }
code, pre, kbd, samp { font-family: var(--td-mono) !important; }

/* ---------------------------------------------------------------- sidebar */
[data-testid="stSidebar"] {
  background:
    radial-gradient(circle at 12% 0%, rgba(53,112,110,.24), transparent 40%),
    linear-gradient(180deg, #102a2d 0%, #0b1f22 100%);
  border-right: 1px solid #1f3b3d;
}
[data-testid="stSidebar"] > div:first-child { padding-top: 1rem; }
[data-testid="stSidebar"] .block-container { padding: 0; }
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 { color: #f2efe5 !important; }
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] label p,
[data-testid="stSidebar"] .stMarkdown p { color: #c8d3cf !important; }
[data-testid="stSidebar"] .stCaption,
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p { color: #91a5a1 !important; font-size: 10.5px !important; line-height: 1.35 !important; }
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] { margin-top: 7px; }
[data-testid="stSidebarUserContent"] div[data-testid="stVerticalBlock"] { gap: .55rem; }
[data-testid="stSidebar"] hr { border-color: rgba(255,255,255,.12); }
[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p {
  color: #c8d3cf !important;
  font-size: 11px !important;
  letter-spacing: .11em;
  text-transform: uppercase;
  font-weight: 500;
}
/* Sidebar fields: light paper field, black value text, dark icons. */
[data-testid="stSidebar"] [data-testid="stSelectbox"] .react-aria-ComboBox > div,
[data-testid="stSidebar"] [data-baseweb="select"] > div,
[data-testid="stSidebar"] [data-testid="stNumberInputContainer"],
[data-testid="stSidebar"] [data-testid="stTextInputRootElement"],
[data-testid="stSidebar"] [data-baseweb="input"] {
  background: #f4f1e8 !important;
  border: 1px solid #f4f1e8 !important;
  border-radius: 2px !important;
  min-height: 38px !important;
}
[data-testid="stSidebar"] [data-testid="stSelectbox"] .react-aria-ComboBox > div:focus-within,
[data-testid="stSidebar"] [data-testid="stNumberInputContainer"]:focus-within,
[data-testid="stSidebar"] [data-testid="stTextInputRootElement"]:focus-within {
  border-color: #8fc7c0 !important;
  box-shadow: 0 0 0 2px rgba(143,199,192,.28) !important;
}
[data-testid="stSidebar"] input,
[data-testid="stSidebar"] textarea,
[data-testid="stSidebar"] [role="combobox"],
[data-testid="stSidebar"] [data-baseweb="select"] div,
[data-testid="stSidebar"] [data-baseweb="input"] input {
  background: transparent !important;
  color: #000 !important;
  -webkit-text-fill-color: #000 !important;
  caret-color: #000;
  font-size: 13px !important;
  opacity: 1 !important;
}
[data-testid="stSidebar"] input::placeholder,
[data-testid="stSidebar"] textarea::placeholder {
  color: #5d6b6d !important;
  -webkit-text-fill-color: #5d6b6d !important;
}
[data-testid="stSidebar"] [data-testid="stSelectbox"] .react-aria-ComboBox button,
[data-testid="stSidebar"] [data-testid="stSelectbox"] .react-aria-ComboBox svg,
[data-testid="stSidebar"] [data-baseweb="select"] svg {
  background: transparent !important;
  color: #132527 !important;
  fill: #132527 !important;
}
[data-testid="stSidebar"] [data-testid="stNumberInput"] button {
  background: transparent !important;
  border-color: transparent !important;
  color: #132527 !important;
}
[data-testid="stSidebar"] [data-testid="stNumberInput"] button:hover { background: #e4dfd2 !important; }
[data-testid="stSidebar"] [data-testid="stNumberInput"] button svg { color: #132527 !important; fill: #132527 !important; }
[data-testid="stSidebar"] [data-testid="stTooltipIcon"] button,
[data-testid="stSidebar"] [data-testid="stTooltipIcon"] svg { color: #8fa7a2 !important; stroke: #8fa7a2 !important; }
/* Disabled fields: same paper, dimmed but still legible. */
[data-testid="stSidebar"] [data-testid="stSelectbox"] .react-aria-ComboBox > div[data-disabled],
[data-testid="stSidebar"] [data-testid="stSelectbox"]:has(input:disabled) .react-aria-ComboBox > div { opacity: .55; }
/* Dropdown menus are portalled to <body>: black option text. */
[data-testid="stSelectboxVirtualDropdown"] [role="option"],
[data-testid="stSelectboxVirtualDropdown"] [role="option"] *,
ul[role="listbox"] li,
ul[role="listbox"] li * {
  color: #000 !important;
  -webkit-text-fill-color: #000 !important;
}
[data-testid="stSelectboxVirtualDropdown"] [role="option"] { font-size: 13px; }
/* Long row labels: let the open menu grow past the narrow sidebar. */
[data-testid="stSelectboxVirtualDropdown"] { min-width: min(430px, calc(100vw - 24px)) !important; }
/* Sidebar segmented filter (All · Weather · Late aircraft). */
[data-testid="stSidebar"] [data-testid="stButtonGroup"],
[data-testid="stSidebar"] [data-testid="stElementContainer"]:has(> [data-testid="stButtonGroup"]) { width: 100% !important; }
[data-testid="stSidebar"] [data-testid="stButtonGroup"] [role="radiogroup"] {
  display: flex;
  flex-wrap: nowrap;
  width: 100% !important;
  max-width: none !important;
  gap: 0;
}
[data-testid="stSidebar"] button[data-variant="segmented_control"] {
  flex: 1 1 auto;
  min-height: 30px;
  padding: 0 6px;
  background: transparent !important;
  border: 1px solid rgba(255,255,255,.2) !important;
  border-radius: 0 !important;
  margin-left: -1px;
}
[data-testid="stSidebar"] button[data-variant="segmented_control"]:first-child { border-radius: 2px 0 0 2px !important; margin-left: 0; }
[data-testid="stSidebar"] button[data-variant="segmented_control"]:last-child { border-radius: 0 2px 2px 0 !important; }
[data-testid="stSidebar"] button[data-variant="segmented_control"] p {
  color: #b9c9c4 !important;
  font-family: var(--td-mono) !important;
  font-size: 9.5px !important;
  letter-spacing: .08em;
  text-transform: uppercase;
  white-space: nowrap;
  overflow: visible !important;
  text-overflow: clip !important;
}
[data-testid="stSidebar"] button[data-variant="segmented_control"]:hover { background: rgba(255,255,255,.07) !important; }
[data-testid="stSidebar"] button[data-variant="segmented_control"][aria-checked="true"] {
  background: #f4f1e8 !important;
  border-color: #f4f1e8 !important;
  position: relative;
  z-index: 1;
}
[data-testid="stSidebar"] button[data-variant="segmented_control"][aria-checked="true"] p { color: #000 !important; font-weight: 600; }
[data-testid="stSidebar"] [role="radiogroup"] label p,
[data-testid="stSidebar"] [data-testid="stCheckbox"] label p { color: #d7e0dc !important; }
[data-testid="stSidebar"] [data-baseweb="checkbox"] div,
[data-testid="stSidebar"] [data-baseweb="radio"] div { border-color: rgba(255,255,255,.4) !important; }
[data-testid="stSidebar"] .stButton > button,
[data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"] {
  width: 100%;
  min-height: 40px;
  background: rgba(255,255,255,.07);
  color: #f4f1e8;
  border: 1px solid rgba(255,255,255,.24);
  border-radius: 2px;
  font-size: 11px;
  letter-spacing: .12em;
  text-transform: uppercase;
  font-weight: 600;
}
[data-testid="stSidebar"] .stButton button p,
[data-testid="stSidebar"] .stButton button span,
[data-testid="stSidebar"] .stButton button div { color: inherit !important; }
[data-testid="stSidebar"] .stButton > button:hover { border-color: #c8d3cf; background: rgba(255,255,255,.12); }
[data-testid="stSidebar"] button[kind="primary"],
[data-testid="stSidebar"] button[data-testid="stBaseButton-primary"] {
  background: #f0ead9 !important;
  color: #102a2d !important;
  border-color: #f0ead9 !important;
}
[data-testid="stSidebar"] button[kind="primary"]:hover,
[data-testid="stSidebar"] button[data-testid="stBaseButton-primary"]:hover {
  background: #fff9e9 !important;
  color: #0b1f22 !important;
}
[data-testid="stSidebar"] details,
[data-testid="stSidebar"] [data-testid="stExpander"] details {
  border: 1px solid rgba(255,255,255,.12);
  background: rgba(255,255,255,.025);
  border-radius: 2px;
}
[data-testid="stSidebar"] [data-testid="stExpander"] summary,
[data-testid="stSidebar"] details summary {
  background: transparent !important;
  border: none !important;
  color: #d7e0dc !important;
}
[data-testid="stSidebar"] details > summary,
[data-testid="stSidebar"] details > summary span,
[data-testid="stSidebar"] details > summary div,
[data-testid="stSidebar"] details summary p,
[data-testid="stSidebar"] details summary * { color: #d7e0dc !important; }
[data-testid="stSidebar"] [data-testid="stExpander"] { border: 1px solid rgba(255,255,255,.12); background: rgba(255,255,255,.02) !important; }
[data-testid="stSidebar"] [data-testid="stAlert"] { color: #132527; }
[data-testid="stSidebar"] [data-testid="stAlert"] p { color: #132527 !important; }
[data-testid="stSidebar"] [data-testid="stAlert"] a { color: #0d5a56 !important; }

/* ---------------------------------------------------------------- widgets */
.stTabs [data-baseweb="tab-list"] {
  gap: 2rem;
  border-bottom: 1px solid var(--td-line);
  margin-bottom: 1.1rem;
}
.stTabs [data-baseweb="tab"] {
  height: auto;
  padding: 0 0 .7rem 0;
  background: transparent;
  color: var(--td-muted);
  font-family: var(--td-display);
  font-size: 17px;
  letter-spacing: .09em;
  text-transform: uppercase;
}
.stTabs [data-baseweb="tab"]:hover { color: var(--td-ink); }
.stTabs [aria-selected="true"] { color: var(--td-ink) !important; }
.stTabs [data-baseweb="tab-highlight"] { background-color: var(--td-teal); height: 2px; }
.stTabs [data-baseweb="tab-border"] { display: none; }

[data-testid="stExpander"] {
  border: 1px solid var(--td-line);
  border-radius: 2px;
  background: rgba(251,250,246,.6);
}
[data-testid="stExpander"] summary {
  font-family: var(--td-mono);
  font-size: 11px;
  letter-spacing: .05em;
  text-transform: uppercase;
  color: var(--td-ink-2);
}
[data-testid="stExpander"] summary:hover { color: var(--td-teal); }

.stButton > button {
  border-radius: 2px;
  font-size: 11px;
  letter-spacing: .11em;
  text-transform: uppercase;
  font-weight: 600;
}
.stDownloadButton > button {
  border-radius: 2px;
  border: 1px solid var(--td-line-strong);
  background: var(--td-surface);
  color: var(--td-ink);
  font-size: 10px;
  letter-spacing: .1em;
  text-transform: uppercase;
}

[data-testid="stAlert"] { border-radius: 2px; }
[data-testid="stCode"] { border-radius: 2px; border: 1px solid var(--td-line); }

/* ---------------------------------------------------------------- brand */
.td-brand { padding: .1rem 0 1.15rem; margin-bottom: .85rem; border-bottom: 1px solid rgba(255,255,255,.14); }
.td-brand-row { display: flex; align-items: baseline; gap: 9px; }
.td-brand-mark {
  font-family: var(--td-display);
  font-size: 33px;
  font-weight: 700;
  letter-spacing: .16em;
  color: #f4f1e8;
  line-height: 1;
}
.td-brand-slash { color: #6ea5a1; font-family: var(--td-mono); font-size: 13px; }
.td-brand-sub {
  margin-top: 7px;
  font-family: var(--td-mono);
  font-size: 9.5px;
  line-height: 1.5;
  letter-spacing: .16em;
  text-transform: uppercase;
  color: #8fa7a2;
}
.td-side-label {
  margin: 1.1rem 0 .35rem;
  font-family: var(--td-mono);
  font-size: 9px;
  letter-spacing: .18em;
  text-transform: uppercase;
  color: #6f8b87;
}
.td-side-note {
  border-left: 2px solid #3d6663;
  padding: 2px 0 2px 10px;
  margin: 10px 0 2px;
  font-size: 11.5px;
  line-height: 1.5;
  color: #9fb2ae;
}
.td-side-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin: 6px 0 0;
}
.td-side-tag {
  border: 1px solid rgba(255,255,255,.2);
  color: #bccbc7;
  padding: 2px 6px;
  font-family: var(--td-mono);
  font-size: 9px;
  letter-spacing: .06em;
  text-transform: uppercase;
}

/* ---------------------------------------------------------------- hero */
.td-hero {
  position: relative;
  overflow: hidden;
  background-color: var(--td-deep);
  background-image:
    linear-gradient(rgba(255,255,255,.035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,.035) 1px, transparent 1px),
    radial-gradient(circle at 82% 12%, rgba(68,135,131,.28), transparent 42%);
  background-size: 44px 44px, 44px 44px, auto;
  border: 1px solid #0a1e20;
  border-radius: 3px;
  padding: 24px 28px 22px;
  color: #f5f2e8;
  box-shadow: 0 18px 42px rgba(9,27,29,.16);
  animation: td-rise .45s ease-out both;
}
.td-hero::after {
  content: "";
  position: absolute;
  right: -160px;
  top: -260px;
  width: 560px;
  height: 560px;
  border: 1px solid rgba(255,255,255,.08);
  border-radius: 50%;
  pointer-events: none;
}
.td-hero-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 18px;
  position: relative;
  z-index: 1;
}
.td-kicker {
  font-family: var(--td-mono);
  font-size: 9.5px;
  letter-spacing: .19em;
  text-transform: uppercase;
  color: #8ba9a5;
}
.td-hero-right { display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; }
.td-hero-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(330px, .75fr);
  gap: 34px;
  align-items: end;
  margin-top: 16px;
  position: relative;
  z-index: 1;
}
.td-route {
  display: flex;
  align-items: baseline;
  gap: 14px;
  font-family: var(--td-display);
  font-weight: 600;
  font-size: clamp(50px, 6.1vw, 82px);
  line-height: .88;
  letter-spacing: .015em;
  color: #f8f5ea;
}
.td-route-arrow { font-family: var(--td-mono); font-size: .38em; color: #7fa6a2; letter-spacing: -.05em; }
.td-flight-line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 9px 14px;
  margin-top: 14px;
  font-family: var(--td-mono);
  font-size: 11.5px;
  letter-spacing: .06em;
  color: #c6d3ce;
}
.td-flight-line b { color: #f5f2e8; font-weight: 500; }
.td-sep { color: #54716e; }
.td-summary {
  margin-top: 15px;
  max-width: 830px;
  font-size: 14px;
  line-height: 1.55;
  color: #b7c8c4;
}
.td-delays {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 5px 15px;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid rgba(255,255,255,.11);
  font-family: var(--td-mono);
  font-size: 10px;
  color: #96aca8;
}
.td-delay-label {
  font-size: 8px;
  letter-spacing: .16em;
  text-transform: uppercase;
  color: #7b9793;
}
.td-delay-item b { color: #f1ede1; font-weight: 500; }
.td-delay-item { white-space: nowrap; }
.td-hero-metrics {
  display: grid;
  grid-template-columns: 1fr 1fr;
  border-top: 1px solid rgba(255,255,255,.14);
  border-left: 1px solid rgba(255,255,255,.14);
}
.td-hero-metric {
  padding: 11px 13px 10px;
  border-right: 1px solid rgba(255,255,255,.14);
  border-bottom: 1px solid rgba(255,255,255,.14);
}
.td-hero-label {
  font-family: var(--td-mono);
  font-size: 8.5px;
  letter-spacing: .17em;
  text-transform: uppercase;
  color: #7f9c98;
  display: flex;
  gap: 6px;
  align-items: center;
}
.td-hero-value {
  margin-top: 5px;
  font-family: var(--td-mono);
  font-size: 20px;
  line-height: 1.1;
  color: #f6f2e6;
  white-space: nowrap;
}
.td-hero-sub { margin-top: 4px; font-size: 10.5px; color: #8da6a1; }

/* ---------------------------------------------------------------- badges */
.td-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 6px;
  border: 1px solid var(--td-line-strong);
  border-radius: 2px;
  font-family: var(--td-mono);
  font-size: 8.5px;
  line-height: 1.35;
  letter-spacing: .07em;
  text-transform: uppercase;
  white-space: nowrap;
  color: var(--td-muted);
  background: transparent;
}
.td-badge-dark { border-color: rgba(255,255,255,.2); color: #a9bdb9; }
.td-real { border-color: #8fb9a4; color: #165f45; background: #edf6f0; }
.td-synth { border-color: #d4b57e; color: #875300; background: #fbf3e4; }
.td-derived { border-color: #a9c1ce; color: #2b5e80; background: #edf4f7; }
.td-green { border-color: #a9cbbb; color: #155c42; background: var(--td-green-bg); }
.td-amber { border-color: #d8bb87; color: #855200; background: var(--td-amber-bg); }
.td-red { border-color: #d7a8a2; color: #922b27; background: var(--td-red-bg); }
.td-blue { border-color: #a8c2d3; color: #2b5e80; background: #edf4f8; }
.td-grey { border-color: var(--td-line); color: var(--td-muted); background: var(--td-surface-2); }
.td-hero .td-real, .td-hero .td-synth, .td-hero .td-derived {
  background: rgba(255,255,255,.06);
  border-color: rgba(255,255,255,.23);
  color: #b9cbc7;
}
.td-hero .td-real { color: #8fc7ad; }
.td-hero .td-synth { color: #dcc38e; }
.td-hero .td-derived { color: #9dc1d6; }

/* ---------------------------------------------------------------- provenance */
.td-prov {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 16px;
  margin-top: 10px;
  padding: 9px 12px;
  border: 1px solid var(--td-line);
  border-top: none;
  background: rgba(251,250,246,.66);
  border-radius: 0 0 3px 3px;
  font-size: 10.5px;
  color: var(--td-muted);
}
.td-prov-item { display: flex; align-items: center; gap: 6px; }
.td-prov-item b { color: var(--td-ink-2); font-weight: 500; }

/* ---------------------------------------------------------------- status strip */
.td-status-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 1px;
  margin-top: 14px;
  background: var(--td-line);
  border: 1px solid var(--td-line);
  box-shadow: var(--td-shadow);
  animation: td-rise .45s .06s ease-out both;
}
.td-stat { background: var(--td-surface); padding: 13px 15px 12px; min-height: 74px; }
.td-stat-label {
  font-family: var(--td-mono);
  font-size: 8.5px;
  letter-spacing: .16em;
  text-transform: uppercase;
  color: var(--td-muted);
}
.td-stat-value {
  margin-top: 7px;
  font-family: var(--td-display);
  font-size: 27px;
  line-height: .95;
  letter-spacing: .03em;
  color: var(--td-ink);
}
.td-stat-value.mono { font-family: var(--td-mono); font-size: 17px; letter-spacing: 0; padding-top: 6px; }
.td-stat-sub { margin-top: 5px; font-size: 10.5px; color: var(--td-muted); }
.td-status-consensus { color: var(--td-green); }
.td-status-fallback { color: var(--td-amber); }
.td-status-escalated { color: var(--td-red); }
.td-status-safe { color: var(--td-green); }
.td-status-unsafe { color: var(--td-red); }

/* ---------------------------------------------------------------- flow */
.td-flow {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
  margin: 18px 0 2px;
}
.td-flow-step {
  border-top: 2px solid var(--td-line);
  padding: 9px 2px 0;
  min-width: 0;
}
.td-flow-step.done { border-top-color: var(--td-teal); }
.td-flow-step.active { border-top-color: var(--td-amber); }
.td-flow-step.skipped { border-top-color: var(--td-line); opacity: .62; }
.td-flow-label {
  font-family: var(--td-mono);
  font-size: 8.5px;
  letter-spacing: .16em;
  text-transform: uppercase;
  color: var(--td-muted);
}
.td-flow-value {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.35;
  color: var(--td-ink-2);
}

/* ---------------------------------------------------------------- headings */
.td-section-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 18px;
  border-bottom: 1px solid var(--td-line);
  padding-bottom: 7px;
  margin: 22px 0 13px;
}
.td-section-kicker {
  font-family: var(--td-mono);
  font-size: 8.5px;
  letter-spacing: .18em;
  text-transform: uppercase;
  color: var(--td-muted);
}
.td-section-title {
  font-family: var(--td-display);
  font-size: 25px;
  line-height: 1;
  letter-spacing: .05em;
  text-transform: uppercase;
  color: var(--td-ink);
}
.td-section-aside { font-family: var(--td-mono); font-size: 10px; color: var(--td-muted); }

/* ---------------------------------------------------------------- topology */
.td-hub-band { margin: 8px 0 4px; }
.td-hub-node {
  position: relative;
  width: min(690px, 100%);
  margin: 0 auto;
  background: var(--td-deep);
  border: 1px solid #0a1e20;
  color: #f4f1e8;
  text-align: center;
  padding: 10px 18px 11px;
  border-radius: 2px;
}
.td-hub-node::after {
  content: "";
  position: absolute;
  left: 50%;
  bottom: -18px;
  height: 18px;
  border-left: 1px dashed var(--td-line-strong);
}
.td-hub-kicker {
  font-family: var(--td-mono);
  font-size: 8.5px;
  letter-spacing: .2em;
  text-transform: uppercase;
  color: #88a5a0;
}
.td-hub-title { margin-top: 4px; font-family: var(--td-display); font-size: 19px; letter-spacing: .04em; }
.td-hub-sub { margin-top: 3px; font-size: 10.5px; color: #9eb2ae; }
.td-spoke-row {
  position: relative;
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-top: 18px;
  padding-top: 12px;
}
.td-spoke-row::before {
  content: "";
  position: absolute;
  top: 0;
  left: 16.67%;
  right: 16.67%;
  border-top: 1px dashed var(--td-line-strong);
}
.td-spoke {
  position: relative;
  background: var(--td-surface);
  border: 1px solid var(--td-line);
  border-top: 2px solid var(--role);
  padding: 10px 12px;
  min-height: 68px;
}
.td-spoke::before {
  content: "";
  position: absolute;
  top: -13px;
  left: 50%;
  height: 12px;
  border-left: 1px dashed var(--td-line-strong);
}
.td-spoke.atc { --role: var(--td-atc); }
.td-spoke.pilot { --role: var(--td-pilot); }
.td-spoke.ground { --role: var(--td-ground); }
.td-spoke-top { display: flex; justify-content: space-between; gap: 8px; align-items: baseline; }
.td-spoke-role {
  font-family: var(--td-display);
  font-size: 18px;
  letter-spacing: .08em;
  color: var(--role);
}
.td-spoke-impl { font-family: var(--td-mono); font-size: 8.5px; letter-spacing: .05em; color: var(--td-muted); }
.td-spoke-meta { margin-top: 5px; font-family: var(--td-mono); font-size: 10px; color: var(--td-ink-2); }
.td-spoke-sub { margin-top: 3px; font-size: 10px; color: var(--td-muted); }

/* ---------------------------------------------------------------- turn + agent cards */
.td-turn {
  display: flex;
  align-items: center;
  gap: 13px;
  margin: 26px 0 12px;
}
.td-turn-num {
  font-family: var(--td-display);
  font-size: 40px;
  line-height: .8;
  color: var(--td-line-strong);
}
.td-turn-title {
  font-family: var(--td-display);
  font-size: 22px;
  letter-spacing: .08em;
  text-transform: uppercase;
  color: var(--td-ink);
}
.td-turn-sub { font-family: var(--td-mono); font-size: 9.5px; color: var(--td-muted); letter-spacing: .05em; }
.td-turn-rule { flex: 1; border-top: 1px solid var(--td-line); }

.td-agent {
  background: var(--td-surface);
  border: 1px solid var(--td-line);
  border-top: 3px solid var(--role);
  border-radius: 2px;
  padding: 15px 15px 14px;
  min-height: 100%;
  box-shadow: 0 1px 0 rgba(19,37,39,.03);
}
.td-agent.atc { --role: var(--td-atc); }
.td-agent.pilot { --role: var(--td-pilot); }
.td-agent.ground { --role: var(--td-ground); }
.td-agent.ghost { border-top-color: var(--td-line-strong); opacity: .62; }
.td-agent-head { display: flex; justify-content: space-between; align-items: center; gap: 10px; }
.td-role { display: flex; align-items: center; gap: 9px; }
.td-role-mark {
  display: grid;
  place-items: center;
  width: 29px;
  height: 29px;
  background: var(--role);
  color: #fffdf6;
  font-family: var(--td-mono);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: .02em;
  border-radius: 1px;
}
.td-role-name {
  font-family: var(--td-display);
  font-size: 22px;
  line-height: 1;
  letter-spacing: .08em;
  text-transform: uppercase;
  color: var(--role);
}
.td-role-sub { margin-top: 3px; font-size: 9.5px; color: var(--td-muted); }
.td-msg-type {
  font-family: var(--td-mono);
  font-size: 8px;
  letter-spacing: .1em;
  text-transform: uppercase;
  color: var(--td-muted);
  border: 1px solid var(--td-line);
  padding: 2px 5px;
  white-space: nowrap;
}
.td-top-choice {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  margin: 12px 0 11px;
  padding: 9px 11px;
  background: var(--td-surface-2);
  border: 1px solid var(--td-line-2);
}
.td-top-label {
  font-family: var(--td-mono);
  font-size: 8px;
  letter-spacing: .14em;
  text-transform: uppercase;
  color: var(--td-muted);
}
.td-top-value { margin-top: 2px; font-size: 11px; color: var(--td-muted); }
.td-top-id {
  font-family: var(--td-mono);
  font-size: 21px;
  font-weight: 500;
  color: var(--role);
  line-height: 1;
}
.td-top-rank { font-family: var(--td-mono); font-size: 8.5px; color: var(--td-muted); margin-top: 3px; text-align: right; }
.td-minihead {
  margin: 12px 0 5px;
  font-family: var(--td-mono);
  font-size: 8.5px;
  letter-spacing: .13em;
  text-transform: uppercase;
  color: var(--td-muted);
  display: flex;
  justify-content: space-between;
  gap: 8px;
}
.td-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin: 0 3px 4px 0;
  padding: 2px 6px;
  border: 1px solid var(--td-line);
  border-radius: 2px;
  font-family: var(--td-mono);
  font-size: 9px;
  line-height: 1.45;
  letter-spacing: .02em;
  background: var(--td-surface-2);
  color: var(--td-ink-2);
}
.td-chip b { font-weight: 600; color: var(--td-ink); }
.td-chip-veto { border-color: #ddb0ab; background: var(--td-red-bg); color: #8f2d28; }
.td-chip-veto b { color: #8f2d28; }
.td-chip-obj { border-color: #d7c9a5; background: #f8f2e2; color: #6e5a24; }
.td-chip-cite { border-color: #b3c9d2; background: #edf4f7; color: #2d5c70; }
.td-chip-counter { border-color: #b9adca; background: #f3eff8; color: #554274; }
.td-chip-good { border-color: #a9cbbb; background: var(--td-green-bg); color: #155c42; }
.td-chip-empty { color: var(--td-muted-2); border-style: dashed; }
.td-rationale {
  border-left: 2px solid color-mix(in srgb, var(--role) 45%, transparent);
  padding: 2px 0 2px 10px;
  margin: 10px 0 6px;
  font-size: 12.5px;
  line-height: 1.55;
  color: #34484a;
}
.td-facts { width: 100%; border-collapse: collapse; }
.td-facts td { padding: 5px 0 4px; border-top: 1px solid var(--td-line-2); vertical-align: top; font-size: 11.2px; line-height: 1.45; word-break: break-word; }
.td-facts td.k {
  width: 31%;
  padding-right: 8px;
  font-family: var(--td-mono);
  font-size: 8.5px;
  letter-spacing: .04em;
  text-transform: uppercase;
  color: var(--td-muted);
}
.td-src {
  display: inline-block;
  margin-left: 4px;
  padding: 0 4px;
  border: 1px solid var(--td-line);
  border-radius: 1px;
  font-family: var(--td-mono);
  font-size: 7.5px;
  letter-spacing: .06em;
  text-transform: uppercase;
  vertical-align: 1px;
}
.td-src-llm { border-color: #9ec2ae; color: #155c42; background: var(--td-green-bg); }
.td-src-stub { border-color: #c9c2b1; color: var(--td-muted); background: var(--td-surface-2); }
.td-src-default { border-color: #d8bb87; color: #855200; background: var(--td-amber-bg); }
.td-citations { margin-top: 4px; }
.td-cite {
  display: block;
  padding: 4px 0 4px 11px;
  border-left: 2px solid #c9d9df;
  font-size: 10.5px;
  color: #3d5559;
  line-height: 1.4;
}
.td-cite.synthetic { color: #7a5d27; }
.td-empty { font-size: 11px; color: var(--td-muted-2); font-style: italic; }

/* ---------------------------------------------------------------- orchestrator card */
.td-orch-card {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(280px, .8fr);
  gap: 20px;
  margin: 16px 0 2px;
  padding: 14px 17px;
  border: 1px dashed var(--td-line-strong);
  background: rgba(248,245,237,.75);
  border-radius: 2px;
}
.td-orch-kicker {
  font-family: var(--td-mono);
  font-size: 8.5px;
  letter-spacing: .17em;
  text-transform: uppercase;
  color: var(--td-muted);
}
.td-orch-title { margin-top: 5px; font-family: var(--td-display); font-size: 19px; letter-spacing: .04em; }
.td-orch-text { margin-top: 4px; font-size: 11.5px; color: var(--td-muted); line-height: 1.5; }
.td-scores { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 8px; }
.td-score {
  display: flex;
  align-items: baseline;
  gap: 6px;
  border: 1px solid var(--td-line);
  background: var(--td-surface);
  padding: 3px 7px;
  font-family: var(--td-mono);
  font-size: 10px;
}
.td-score b { font-size: 12px; font-weight: 600; }
.td-score.top { border-color: #a9cbbb; background: var(--td-green-bg); }
.td-orch-side { border-left: 1px solid var(--td-line); padding-left: 17px; }
.td-orch-side .td-minihead { margin-top: 0; }
.td-orch-line { display: flex; justify-content: space-between; gap: 8px; padding: 4px 0; border-top: 1px solid var(--td-line-2); font-size: 11px; }
.td-orch-line b { font-family: var(--td-mono); font-weight: 500; }

/* ---------------------------------------------------------------- ballots */
.td-vote { display: flex; justify-content: space-between; align-items: flex-start; gap: 9px; padding: 5px 0; border-top: 1px solid var(--td-line-2); font-size: 11px; }
.td-vote:first-of-type { border-top: none; }
.td-vote-id { font-family: var(--td-mono); font-weight: 500; color: var(--td-ink-2); }
.td-vote-reason { font-size: 9.5px; color: var(--td-muted); margin-top: 2px; }
.td-vote-yes { font-family: var(--td-mono); font-size: 8.5px; letter-spacing: .05em; color: var(--td-green); white-space: nowrap; }
.td-vote-no { font-family: var(--td-mono); font-size: 8.5px; letter-spacing: .05em; color: var(--td-red); white-space: nowrap; }
.td-ballot-rank { margin-top: 7px; font-size: 10.5px; color: var(--td-muted); }

/* ---------------------------------------------------------------- banner */
.td-banner {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  padding: 11px 14px;
  border: 1px solid var(--td-line);
  border-left: 4px solid var(--td-teal);
  background: var(--td-surface);
  margin: 12px 0;
  border-radius: 2px;
}
.td-banner-red { border-left-color: var(--td-red); background: var(--td-red-bg); border-color: #e0b7b1; }
.td-banner-amber { border-left-color: var(--td-amber); background: var(--td-amber-bg); border-color: #dec49a; }
.td-banner-green { border-left-color: var(--td-green); background: var(--td-green-bg); border-color: #b3d2c2; }
.td-banner-title {
  font-family: var(--td-display);
  font-size: 17px;
  line-height: 1.05;
  letter-spacing: .05em;
  text-transform: uppercase;
}
.td-banner-text { margin-top: 3px; font-size: 11.5px; line-height: 1.5; color: var(--td-ink-2); }
.td-banner-mark { font-family: var(--td-mono); font-size: 10px; color: var(--td-muted); padding-top: 2px; }

/* ---------------------------------------------------------------- tables */
.td-table-wrap { border: 1px solid var(--td-line); background: var(--td-surface); overflow-x: auto; border-radius: 2px; }
table.td-table { width: 100%; border-collapse: collapse; min-width: 740px; }
.td-table th {
  padding: 8px 9px;
  background: #efede5;
  border-bottom: 1px solid var(--td-line);
  font-family: var(--td-mono);
  font-size: 8px;
  font-weight: 500;
  letter-spacing: .1em;
  text-transform: uppercase;
  color: var(--td-muted);
  text-align: left;
  white-space: nowrap;
}
.td-table td {
  padding: 7px 9px;
  border-bottom: 1px solid var(--td-line-2);
  font-size: 12px;
  line-height: 1.4;
  color: var(--td-ink-2);
  vertical-align: top;
  white-space: nowrap;
}
.td-table tr:last-child td { border-bottom: none; }
.td-table .mono { font-family: var(--td-mono); font-size: 11px; }
.td-table .num { font-family: var(--td-mono); font-size: 11px; text-align: right; }
.td-table .wrap { white-space: normal; min-width: 180px; }
.td-table .muted { color: var(--td-muted); }
.td-table tr.committed td { background: #eaf4ed; }
.td-table tr.committed td:first-child { box-shadow: inset 3px 0 0 var(--td-green); }
.td-table tr.shortlisted td { background: #eef4f8; }
.td-table tr.shortlisted td:first-child { box-shadow: inset 3px 0 0 var(--td-blue); }
.td-table tr.vetoed td { background: #fcf6f4; color: #6d7a7b; }
.td-table tr.vetoed td:first-child { box-shadow: inset 3px 0 0 #c68a83; }
.td-table tr.rejected td { background: #fcf6f4; color: #6d7a7b; }
.td-table tr.rejected td:first-child { box-shadow: inset 3px 0 0 #c68a83; }
.td-table tr.feasible td:first-child { box-shadow: inset 3px 0 0 var(--td-line-strong); }
.td-opt-id { font-family: var(--td-mono); font-weight: 600; font-size: 11px; color: var(--td-ink); }
.td-opt-origin {
  display: inline-block;
  margin-left: 4px;
  font-family: var(--td-mono);
  font-size: 7.5px;
  letter-spacing: .05em;
  color: var(--td-muted);
  border: 1px solid var(--td-line);
  padding: 0 3px;
  vertical-align: 1px;
}
.td-veto-list { display: flex; flex-wrap: wrap; gap: 3px; max-width: 260px; white-space: normal; }
.td-opt-veto { margin-top: 3px; max-width: 170px; font-family: var(--td-mono); font-size: 8px; line-height: 1.35; letter-spacing: .01em; color: #9a4a44; white-space: normal; }
.td-time-arrow { color: var(--td-muted-2); font-family: var(--td-mono); font-size: 9px; }
.td-legend { display: flex; flex-wrap: wrap; gap: 10px 18px; margin: 9px 0 0; font-size: 10px; color: var(--td-muted); }
.td-legend-item { display: flex; align-items: center; gap: 5px; }
.td-swatch { width: 11px; height: 11px; border: 1px solid var(--td-line-strong); display: inline-block; }
.td-swatch.committed { background: #eaf4ed; border-left: 3px solid var(--td-green); }
.td-swatch.shortlisted { background: #eef4f8; border-left: 3px solid var(--td-blue); }
.td-swatch.vetoed { background: #fcf6f4; border-left: 3px solid #c68a83; }
.td-swatch.feasible { background: var(--td-surface); border-left: 3px solid var(--td-line-strong); }
.td-table-note { margin-top: 7px; font-size: 10.5px; color: var(--td-muted); }

/* ---------------------------------------------------------------- resolution */
.td-resolution {
  border: 1px solid #b7d2c3;
  background: linear-gradient(135deg, #f5faf6 0%, #fbfaf6 65%);
  border-left: 5px solid var(--td-green);
  border-radius: 2px;
  padding: 18px 21px 17px;
}
.td-resolution.fallback { border-color: #ddc49a; border-left-color: var(--td-amber); background: linear-gradient(135deg, #fcf5e8 0%, #fbfaf6 65%); }
.td-resolution.escalated { border-color: #ddb3ad; border-left-color: var(--td-red); background: linear-gradient(135deg, #fcf0ee 0%, #fbfaf6 65%); }
.td-res-top { display: flex; justify-content: space-between; align-items: flex-start; gap: 22px; }
.td-res-label { font-family: var(--td-mono); font-size: 8.5px; letter-spacing: .18em; text-transform: uppercase; color: var(--td-muted); }
.td-res-status { margin-top: 3px; font-family: var(--td-display); font-size: 48px; line-height: .86; letter-spacing: .05em; color: var(--td-green); }
.td-resolution.fallback .td-res-status { color: var(--td-amber); }
.td-resolution.escalated .td-res-status { color: var(--td-red); }
.td-res-reason { margin-top: 9px; max-width: 760px; font-size: 12.5px; line-height: 1.55; color: var(--td-ink-2); }
.td-turn-box { text-align: right; min-width: 120px; }
.td-turn-count { font-family: var(--td-mono); font-size: 22px; color: var(--td-ink); }
.td-turn-count small { font-size: 10px; color: var(--td-muted); }
.td-turn-dots { display: flex; gap: 4px; justify-content: flex-end; margin-top: 6px; }
.td-turn-dot { width: 22px; height: 7px; background: var(--td-line); }
.td-turn-dot.on { background: var(--td-green); }
.td-resolution.fallback .td-turn-dot.on { background: var(--td-amber); }
.td-resolution.escalated .td-turn-dot.on { background: var(--td-red); }
.td-turn-cap { margin-top: 5px; font-family: var(--td-mono); font-size: 8.5px; letter-spacing: .06em; color: var(--td-muted); }
.td-res-option {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 22px;
  align-items: baseline;
  margin-top: 15px;
  padding-top: 12px;
  border-top: 1px solid rgba(19,37,39,.1);
}
.td-res-option-main { font-family: var(--td-display); font-size: 23px; letter-spacing: .04em; }
.td-res-option-main b { font-family: var(--td-mono); font-size: 19px; font-weight: 600; color: var(--td-green); }
.td-resolution.fallback .td-res-option-main b { color: var(--td-amber); }
.td-res-option-item { font-size: 11.5px; color: var(--td-muted); }
.td-res-option-item b { font-family: var(--td-mono); font-size: 12px; font-weight: 500; color: var(--td-ink-2); }
.td-cost-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-top: 14px; }
.td-cost {
  border: 1px solid var(--td-line);
  background: rgba(251,250,246,.7);
  padding: 8px 10px;
}
.td-cost-label { font-family: var(--td-mono); font-size: 8px; letter-spacing: .12em; text-transform: uppercase; color: var(--td-muted); }
.td-cost-value { margin-top: 3px; font-family: var(--td-mono); font-size: 17px; color: var(--td-ink); }
.td-cost-total { border-color: var(--td-line-strong); background: var(--td-surface); }

/* ---------------------------------------------------------------- checks */
.td-check-summary { display: flex; flex-wrap: wrap; gap: 10px 18px; align-items: center; margin: 9px 0 10px; font-size: 11.5px; color: var(--td-muted); }
.td-check-badge { font-family: var(--td-mono); font-size: 9px; letter-spacing: .08em; text-transform: uppercase; padding: 3px 7px; border: 1px solid; }
.td-check-badge.pass { color: var(--td-green); border-color: #a9cbbb; background: var(--td-green-bg); }
.td-check-badge.fail { color: var(--td-red); border-color: #d7a8a2; background: var(--td-red-bg); }
.td-check-table { width: 100%; border-collapse: collapse; }
.td-check-table th {
  background: #efede5;
  border-bottom: 1px solid var(--td-line);
  padding: 7px 8px;
  text-align: left;
  font-family: var(--td-mono);
  font-size: 8px;
  letter-spacing: .08em;
  text-transform: uppercase;
  color: var(--td-muted);
  white-space: nowrap;
}
.td-check-table td { border-bottom: 1px solid var(--td-line-2); padding: 7px 8px; font-size: 11px; vertical-align: top; }
.td-check-table tr:last-child td { border-bottom: none; }
.td-check-id { font-family: var(--td-mono); font-size: 10px; font-weight: 500; color: var(--td-ink); }
.td-check-detail { margin-top: 2px; font-size: 9.5px; color: var(--td-muted); line-height: 1.4; white-space: normal; }
.td-check-pass { font-family: var(--td-mono); font-size: 9px; color: var(--td-green); letter-spacing: .05em; }
.td-check-fail { font-family: var(--td-mono); font-size: 9px; color: var(--td-red); letter-spacing: .05em; }
.td-unit { font-family: var(--td-mono); font-size: 8.5px; color: var(--td-muted); }

/* ---------------------------------------------------------------- safety */
.td-safety-card {
  border: 1px solid #e0b7b1;
  border-left: 4px solid var(--td-red);
  background: var(--td-red-bg);
  padding: 14px 16px;
  margin-bottom: 10px;
  border-radius: 2px;
}
.td-safety-head { display: flex; justify-content: space-between; align-items: baseline; gap: 14px; }
.td-safety-title { font-family: var(--td-display); font-size: 20px; letter-spacing: .04em; text-transform: uppercase; color: #7f2824; }
.td-safety-meta { font-family: var(--td-mono); font-size: 8.5px; letter-spacing: .06em; color: #8d5a55; text-transform: uppercase; }
.td-safety-text { margin-top: 4px; font-size: 12px; line-height: 1.5; color: #5e2f2b; }
.td-safety-facts { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 4px; }
.td-safety-fact { background: rgba(255,255,255,.55); border: 1px solid #e1bcb6; padding: 3px 6px; font-family: var(--td-mono); font-size: 9px; color: #7d3c36; }
.td-safety-option { font-family: var(--td-mono); font-size: 10px; color: #7f2824; border-bottom: 1px dashed #ce9c96; }
.td-gate {
  border: 1px solid #b9d5c6;
  border-left: 4px solid var(--td-green);
  background: var(--td-green-bg);
  padding: 13px 16px;
  margin-bottom: 14px;
}
.td-gate.fail { border-color: #ddb3ad; border-left-color: var(--td-red); background: var(--td-red-bg); }
.td-gate.idle { border-color: var(--td-line); border-left-color: var(--td-line-strong); background: var(--td-surface-2); }
.td-gate-title { font-family: var(--td-display); font-size: 22px; letter-spacing: .05em; text-transform: uppercase; }
.td-gate-text { margin-top: 3px; font-size: 11.5px; line-height: 1.5; color: var(--td-ink-2); }
.td-gate-meta { margin-top: 7px; display: flex; flex-wrap: wrap; gap: 6px; }

/* ---------------------------------------------------------------- audit */
.td-chain {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 18px;
  border: 1px solid #b7d2c3;
  background: var(--td-green-bg);
  border-left: 4px solid var(--td-green);
  padding: 13px 16px;
  margin-bottom: 14px;
}
.td-chain.broken { border-color: #ddb3ad; background: var(--td-red-bg); border-left-color: var(--td-red); }
.td-chain-title { font-family: var(--td-display); font-size: 24px; letter-spacing: .05em; text-transform: uppercase; color: var(--td-green); }
.td-chain.broken .td-chain-title { color: var(--td-red); }
.td-chain-meta { font-family: var(--td-mono); font-size: 9.5px; color: var(--td-muted); }
.td-chain-hash { font-family: var(--td-mono); font-size: 10px; color: var(--td-ink-2); }
.td-timeline { width: 100%; border-collapse: collapse; }
.td-timeline th {
  background: #efede5;
  border-bottom: 1px solid var(--td-line);
  padding: 7px 8px;
  text-align: left;
  font-family: var(--td-mono);
  font-size: 8px;
  letter-spacing: .1em;
  text-transform: uppercase;
  color: var(--td-muted);
  white-space: nowrap;
}
.td-timeline td { border-bottom: 1px solid var(--td-line-2); padding: 6px 8px; font-size: 10.5px; vertical-align: top; }
.td-timeline tr:last-child td { border-bottom: none; }
.td-timeline tr.safety td { background: var(--td-red-bg); }
.td-timeline tr.commit td { background: var(--td-green-bg); }
.td-seq { font-family: var(--td-mono); font-size: 9px; color: var(--td-muted); }
.td-actor { font-family: var(--td-mono); font-size: 9px; letter-spacing: .04em; }
.td-actor-ORCHESTRATOR { color: var(--td-ink); }
.td-actor-ATC { color: var(--td-atc); }
.td-actor-PILOT { color: var(--td-pilot); }
.td-actor-GROUND { color: var(--td-ground); }
.td-actor-FALLBACK { color: var(--td-amber); }
.td-event { font-family: var(--td-mono); font-size: 9px; color: var(--td-ink-2); }
.td-event-summary { color: var(--td-muted); white-space: normal; }
.td-context-table { width: 100%; border-collapse: collapse; }
.td-context-table th {
  background: #efede5;
  border-bottom: 1px solid var(--td-line);
  padding: 7px 8px;
  text-align: left;
  font-family: var(--td-mono);
  font-size: 8px;
  letter-spacing: .08em;
  text-transform: uppercase;
  color: var(--td-muted);
}
.td-context-table td { border-bottom: 1px solid var(--td-line-2); padding: 7px 8px; font-size: 10.5px; }
.td-hash { font-family: var(--td-mono); font-size: 9.5px; color: var(--td-ink-2); }
.td-hash-diff { color: var(--td-teal); }
.td-manifest-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1px; background: var(--td-line); border: 1px solid var(--td-line); }
.td-manifest-cell { background: var(--td-surface); padding: 10px 12px; }
.td-manifest-label { font-family: var(--td-mono); font-size: 7.5px; letter-spacing: .12em; text-transform: uppercase; color: var(--td-muted); }
.td-manifest-value { margin-top: 4px; font-family: var(--td-mono); font-size: 10px; color: var(--td-ink-2); word-break: normal; overflow-wrap: anywhere; }
.td-manifest-value.big { font-family: var(--td-mono); font-size: 12px; line-height: 1.45; letter-spacing: 0; word-break: normal; overflow-wrap: normal; }

/* ---------------------------------------------------------------- misc */
.td-panel { background: var(--td-surface); border: 1px solid var(--td-line); border-radius: 2px; padding: 16px 18px; }
.td-note { font-size: 11px; color: var(--td-muted); line-height: 1.55; }
.td-rule { border-top: 1px solid var(--td-line); margin: 18px 0; }
.td-footer {
  margin-top: 34px;
  padding-top: 12px;
  border-top: 1px solid var(--td-line);
  display: flex;
  justify-content: space-between;
  gap: 18px;
  flex-wrap: wrap;
  font-family: var(--td-mono);
  font-size: 8.5px;
  letter-spacing: .06em;
  color: var(--td-muted);
}
.td-empty-state {
  border: 1px dashed var(--td-line-strong);
  background: rgba(251,250,246,.6);
  padding: 34px;
  text-align: center;
}
.td-empty-state h3 { font-size: 27px !important; letter-spacing: .06em !important; text-transform: uppercase; }
.td-empty-state p { max-width: 500px; margin: 8px auto 0; color: var(--td-muted); font-size: 13px; line-height: 1.55; }
.td-json { font-family: var(--td-mono); font-size: 10px; }

/* ---------------------------------------------------------------- richer log: agents */
:root {
  --td-shield: #34508a;
  --td-shield-bg: #eef1f8;
  --td-shield-line: #b9c5de;
}
.td-tag-row { margin: 2px 0 4px; }
.td-chip-muted { border-color: var(--td-line); background: transparent; color: var(--td-muted); border-style: dashed; }
.td-reasons {
  margin: 4px 0 6px;
  padding: 5px 8px;
  border: 1px solid var(--td-line-2);
  background: var(--td-surface-2);
  font-size: 10.5px;
  line-height: 1.45;
  color: var(--td-ink-2);
}
.td-reasons b {
  font-family: var(--td-mono);
  font-size: 8px;
  letter-spacing: .1em;
  text-transform: uppercase;
  color: var(--td-muted);
  margin-right: 5px;
}
.td-compromised {
  display: flex;
  gap: 7px;
  align-items: baseline;
  margin: 4px 0 6px;
  padding: 5px 8px;
  border: 1px solid #e0b7b1;
  border-left: 3px solid var(--td-red);
  background: var(--td-red-bg);
  font-size: 10.5px;
  line-height: 1.45;
  color: #6c2a26;
}
.td-compromised-tag, .td-inject-tag, .td-block-tag {
  display: inline-block;
  padding: 1px 5px;
  border: 1px solid;
  font-family: var(--td-mono);
  font-size: 8px;
  letter-spacing: .08em;
  text-transform: uppercase;
  white-space: nowrap;
}
.td-compromised-tag { color: #8f2d28; border-color: #d7a8a2; background: #fff5f3; }
.td-block-tag { color: #8f2d28; border-color: #e5c3be; background: transparent; }
.td-inject-tag { color: var(--td-shield); border-color: var(--td-shield-line); background: #f7f8fc; }
.td-compromised-banner {
  margin: 10px 0 0;
  padding: 5px 9px;
  background: var(--td-red);
  color: #fff8f6;
  font-family: var(--td-mono);
  font-size: 9px;
  letter-spacing: .1em;
  text-transform: uppercase;
}
.td-spoke-marks { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }
.td-usage-line b { font-weight: 500; letter-spacing: .08em; text-transform: uppercase; font-size: 8px; color: var(--td-ink-2); }
.td-usage-line {
  margin: 2px 0 6px;
  font-family: var(--td-mono);
  font-size: 9px;
  color: var(--td-muted);
}
.td-usage-cached {
  padding: 0 4px;
  border: 1px solid #a8c2d3;
  background: #edf4f8;
  color: var(--td-blue);
  font-family: var(--td-mono);
  font-size: 8.5px;
  letter-spacing: .04em;
}
.td-usage-repaired {
  padding: 0 4px;
  border: 1px solid #d8bb87;
  background: var(--td-amber-bg);
  color: #855200;
  font-family: var(--td-mono);
  font-size: 8.5px;
}
.td-facts tr.td-fact-default td { background: var(--td-amber-bg); }
.td-inject-flag {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: baseline;
  margin: 6px 0 2px;
  padding: 5px 8px;
  border: 1px solid var(--td-shield-line);
  border-left: 3px solid var(--td-shield);
  background: var(--td-shield-bg);
  font-size: 10.5px;
  color: #2c3f63;
}
.td-row-cached td { background: #f3f7fa; }
.td-source-note { font-family: var(--td-mono); font-size: 8.5px; color: var(--td-muted-2); margin-top: 6px; }

/* ---------------------------------------------------------------- commit gate badge */
.td-gate-badge {
  display: inline-block;
  padding: 4px 9px;
  border: 1px solid;
  font-family: var(--td-mono);
  font-size: 9.5px;
  letter-spacing: .06em;
}
.td-gate-badge b { letter-spacing: .14em; text-transform: uppercase; font-weight: 600; margin-right: 4px; }
.td-gate-badge.pass { color: var(--td-green); border-color: #a9cbbb; background: var(--td-green-bg); }
.td-gate-badge.fail { color: var(--td-red); border-color: #d7a8a2; background: var(--td-red-bg); }
.td-gate-badge.idle { color: var(--td-muted); border-color: var(--td-line); background: var(--td-surface-2); }
.td-gate-steps { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 6px; }
.td-gate-step { font-family: var(--td-mono); font-size: 9.5px; padding: 3px 7px; border: 1px solid; }
.td-gate-step.fail { color: var(--td-red); border-color: #d7a8a2; background: #fff; }
.td-gate-step.pass { color: var(--td-green); border-color: #a9cbbb; background: #fff; }

/* ---------------------------------------------------------------- safety layers */
.td-layers { display: grid; grid-template-columns: 1fr 1fr; gap: 1px; background: var(--td-line); border: 1px solid var(--td-line); margin-bottom: 14px; }
.td-layer { display: flex; gap: 14px; padding: 14px 16px; background: var(--td-surface); }
.td-layer-num {
  flex: none;
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  font-family: var(--td-display);
  font-size: 22px;
  color: #fff;
}
.layer-inject { border-top: 3px solid var(--td-shield); }
.layer-inject .td-layer-num { background: var(--td-shield); }
.layer-block { border-top: 3px solid var(--td-red); }
.layer-block .td-layer-num { background: var(--td-red); }
.td-layer-kicker { font-family: var(--td-mono); font-size: 8.5px; letter-spacing: .14em; text-transform: uppercase; color: var(--td-muted); }
.td-layer-title { margin-top: 3px; font-family: var(--td-display); font-size: 19px; letter-spacing: .04em; color: var(--td-ink); }
.td-layer-text { margin-top: 3px; font-size: 11.5px; line-height: 1.5; color: var(--td-ink-2); }
.td-inject-card {
  border: 1px solid var(--td-shield-line);
  border-left: 4px solid var(--td-shield);
  background: var(--td-shield-bg);
  padding: 14px 16px;
  margin-bottom: 10px;
}
.td-inject-title { font-family: var(--td-display); font-size: 20px; letter-spacing: .04em; text-transform: uppercase; color: #2c3f63; }
.td-inject-quote {
  margin: 9px 0 8px;
  padding: 8px 12px;
  border-left: 2px solid var(--td-shield-line);
  background: #fbfcfe;
  font-family: var(--td-mono);
  font-size: 11px;
  line-height: 1.55;
  color: #34405a;
}
.td-inject-quote mark { background: #dfe5f3; color: #1f3563; padding: 0 2px; border-bottom: 1px solid var(--td-shield); }
.td-chip-inject { border-color: var(--td-shield-line); background: #fff; color: var(--td-shield); }
.td-inject-handling { margin-top: 6px; font-size: 11px; color: #34405a; }
.td-inject-handling b { font-family: var(--td-mono); font-size: 8px; letter-spacing: .12em; text-transform: uppercase; color: var(--td-shield); margin-right: 5px; }
.td-block-rows { margin-top: 8px; }
.td-block-row { display: flex; gap: 10px; align-items: baseline; padding: 4px 0; border-top: 1px solid #efd4cf; }
.td-block-row:first-child { border-top: none; }
.td-block-row .td-safety-option { min-width: 74px; }
.td-block-ids { display: flex; flex-wrap: wrap; gap: 0; }

/* ---------------------------------------------------------------- AI-off matrix */
.td-xmatrix { min-width: 640px; }
.td-xmatrix td.td-x-pass { font-family: var(--td-mono); font-size: 9.5px; color: var(--td-green); }
.td-xmatrix td.td-x-fail { white-space: normal; }
.td-xmatrix td.td-x-skip { font-family: var(--td-mono); font-size: 9px; color: var(--td-muted-2); }

/* ---------------------------------------------------------------- audit additions */
.td-timeline tr.inject td { background: var(--td-shield-bg); }
.td-timeline tr.muted td { color: var(--td-muted); }
.td-hash-chip { display: inline-flex; align-items: center; gap: 5px; }
.td-hash-chip::before { content: ""; width: 9px; height: 9px; background: var(--sw); flex: none; }
.td-hash.muted { color: var(--td-muted-2); }
.td-context-table tr.td-turn-first td { border-top: 2px solid var(--td-line); }
.td-indep-facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 8px; margin-bottom: 10px; }
.td-indep-fact { border: 1px solid var(--td-line); border-left: 3px solid var(--td-line-strong); background: var(--td-surface); padding: 8px 10px; }
.td-indep-fact b { display: block; font-family: var(--td-mono); font-size: 8.5px; letter-spacing: .12em; text-transform: uppercase; color: var(--td-muted); }
.td-indep-fact span { display: block; margin-top: 3px; font-size: 11.5px; line-height: 1.45; color: var(--td-ink-2); }
.td-indep-fact.good { border-left-color: var(--td-green); }
.td-indep-fact.warn { border-left-color: var(--td-amber); }
.td-indep-fact.info { border-left-color: var(--td-blue); }

@media (max-width: 820px) {
  .td-layers { grid-template-columns: 1fr; }
}

@keyframes td-rise {
  from { opacity: 0; transform: translateY(7px); }
  to { opacity: 1; transform: translateY(0); }
}

@media (prefers-reduced-motion: reduce) {
  .td-hero, .td-status-grid { animation: none; }
}

@media (max-width: 1180px) {
  .td-hero-grid { grid-template-columns: 1fr; gap: 20px; }
  .td-status-grid { grid-template-columns: repeat(3, 1fr); }
  .td-manifest-grid { grid-template-columns: repeat(2, 1fr); }
  .td-cost-grid { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 820px) {
  .block-container { padding-left: 1rem; padding-right: 1rem; }
  .td-route { font-size: 46px; }
  .td-status-grid { grid-template-columns: repeat(2, 1fr); }
  .td-flow { grid-template-columns: repeat(2, 1fr); }
  .td-spoke-row { grid-template-columns: 1fr; }
  .td-spoke-row::before { display: none; }
  .td-spoke::before { display: none; }
  .td-hub-node::after { display: none; }
  .td-orch-card { grid-template-columns: 1fr; }
  .td-orch-side { border-left: none; padding-left: 0; border-top: 1px solid var(--td-line); padding-top: 10px; }
  .td-res-top { flex-direction: column; }
  .td-turn-box { text-align: left; }
  .td-turn-dots { justify-content: flex-start; }
  .td-manifest-grid { grid-template-columns: 1fr; }
}
</style>
"""


def inject(st) -> None:
    st.markdown(CSS, unsafe_allow_html=True)
