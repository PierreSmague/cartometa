// ==UserScript==
// @name         Cartometa Extension for Geoguessr
// @namespace    perso.geoguessr.cartometa
// @version      1.51
// @description  Use Cartometa directly within GeoGuessr: metas pop up automatically after each guess (with the meta's footprint drawn on your own results map), plus a direct link to explore the metas for any location.
// @author       ValPé
// @match        https://www.geoguessr.com/*
// @match        https://cartometa.com/*
// @grant        none
// @license      MIT
// @run-at       document-start
// @downloadURL https://update.greasyfork.org/scripts/589913/Cartometa%20Extension%20for%20Geoguessr.user.js
// @updateURL https://update.greasyfork.org/scripts/589913/Cartometa%20Extension%20for%20Geoguessr.meta.js
// ==/UserScript==

(function () {
  'use strict';

  // ---------------------------------------------------------------
  // User settings, stored in localStorage (no Tampermonkey permission
  // needed — unlike GM_setValue, which once caused a full script outage
  // after a re-authorization prompt was declined). Designed to be easy
  // to extend: add a key to DEFAULT_SETTINGS and a matching control in
  // the settings panel below.
  //
  // Cross-origin note: localStorage is per-site. Settings saved here
  // (on geoguessr.com) are NOT automatically visible on cartometa.com.
  // Settings that must also apply on Cartometa (zoom, color) are
  // explicitly passed through the data already exchanged between the
  // two sites (same mechanism used for coordinates).
  // ---------------------------------------------------------------
  const CLE_PARAMETRES = "cartometa_parametres";

  const PARAMETRES_PAR_DEFAUT = {
    apercuAutoParRound: true, // auto-open the metas preview after each round (classic/Challenge)
    zoomCartometa: 6, // initial zoom level on Cartometa
    largeurFenetreApercu: 700, // width (px) of the metas preview window
    couleurAccent: "#5EBF82", // accent color for buttons/highlights
    nombreMetas: 14, // number of metas fetched per preview
    opaciteSilhouette: 25, // fill opacity (%) of the footprint polygon drawn on GeoGuessr's map, 0 = outline only
    positionApercuGauche: null, // last dragged position (px) of the metas preview window, null = default corner
    positionApercuHaut: null,
  };

  // Lightens a hex color by a given ratio (0-1), mixing it towards
  // white — used for the slider thumb now that the track itself is
  // much fainter (see its reduced opacity below).
  function eclaircirCouleur(hex, ratio) {
    const m = hex.replace("#", "");
    if (m.length !== 6) return hex;
    const r = Math.min(255, Math.round(parseInt(m.substring(0, 2), 16) + (255 - parseInt(m.substring(0, 2), 16)) * ratio));
    const g = Math.min(255, Math.round(parseInt(m.substring(2, 4), 16) + (255 - parseInt(m.substring(2, 4), 16)) * ratio));
    const b = Math.min(255, Math.round(parseInt(m.substring(4, 6), 16) + (255 - parseInt(m.substring(4, 6), 16)) * ratio));
    return `rgb(${r},${g},${b})`;
  }

  function obtenirParametres() {
    try {
      const brut = localStorage.getItem(CLE_PARAMETRES);
      if (!brut) return { ...PARAMETRES_PAR_DEFAUT };
      return { ...PARAMETRES_PAR_DEFAUT, ...JSON.parse(brut) };
    } catch (e) {
      return { ...PARAMETRES_PAR_DEFAUT };
    }
  }

  // ---- Cartometa URL format — confirmed 2026-08-04 ----
  // https://cartometa.com/#{lat},{lng},{zoom}
  //   - lat/lng rounded to 4 decimals (~11 m precision, plenty for a
  //     GeoGuessr round)
  //   - zoom: initial map zoom, user-configurable (see
  //     PARAMETRES_PAR_DEFAUT.zoomCartometa)
  function buildCartometaUrl(lat, lng) {
    const zoom = obtenirParametres().zoomCartometa;
    const latArrondi = lat.toFixed(4);
    const lngArrondi = lng.toFixed(4);
    return `https://cartometa.com/#${latArrondi},${lngArrondi},${zoom}`;
  }

  function sauvegarderParametres(parametres) {
    try {
      localStorage.setItem(CLE_PARAMETRES, JSON.stringify(parametres));
    } catch (e) {
      // fine if unavailable (strict private browsing, etc.), settings
      // just won't persist
    }
  }

  // Last closed metas preview (manually, or auto-closed on round
  // change): lets it be reopened via the small 🖼️ icon next to the
  // settings button, in case it was closed by accident.
  let dernierApercuFerme = null; // { lat, lng } or null if nothing was closed yet

  function afficherIconeReouverture() {
    let icone = document.getElementById("cartometa-icone-reouverture");
    if (!icone) {
      icone = document.createElement("div");
      icone.id = "cartometa-icone-reouverture";
      icone.textContent = "↺";
      icone.style.color = "#fff";
      icone.style.filter = "drop-shadow(0 1px 3px rgba(0,0,0,0.9))";
      icone.title = "Reopen the last metas preview window";
      icone.style.position = "fixed";
      icone.style.bottom = "16px";
      icone.style.left = "88px"; // right of the settings gear (⚙️, 16px) and the auto-show toggle (🖼️, 52px), 24px wide each + 12px gaps
      icone.style.fontSize = "22px";
      icone.style.fontWeight = "bold";
      icone.style.cursor = "pointer";
      icone.style.zIndex = "999999";
      icone.style.opacity = "0.6";
      icone.addEventListener("mouseenter", () => (icone.style.opacity = "1"));
      icone.addEventListener("mouseleave", () => (icone.style.opacity = "0.6"));
      icone.addEventListener("click", () => {
        if (dernierApercuFerme) {
          ouvrirApercuMetas(dernierApercuFerme.lat, dernierApercuFerme.lng, true);
        }
      });
      document.body.appendChild(icone);
    }
    icone.style.display = "block";
  }

  function masquerIconeReouverture() {
    const icone = document.getElementById("cartometa-icone-reouverture");
    if (icone) icone.style.display = "none";
  }

  // Quick on/off toggle for "auto-show metas preview after each round",
  // right next to the settings gear — a single click flips the same
  // setting the settings panel's checkbox controls, without having to
  // open the panel. Shows a strike-through over the 🖼️ icon when
  // disabled, kept in sync with the panel's checkbox in both directions.
  function mettreAJourIconeBasculeAutoShow() {
    const barre = document.getElementById("cartometa-barre-bascule-auto-show");
    if (!barre) return;
    barre.style.display = obtenirParametres().apercuAutoParRound ? "none" : "block";
  }

  function ajouterBoutonBasculeAutoShow() {
    if (document.getElementById("cartometa-bascule-auto-show")) return;

    const bouton = document.createElement("div");
    bouton.id = "cartometa-bascule-auto-show";
    bouton.title = "Toggle auto-show metas preview after each round";
    bouton.style.position = "fixed";
    bouton.style.bottom = "16px";
    bouton.style.left = "52px"; // right next to the settings gear (⚙️, at left:16px, 24px wide + 12px gap)
    bouton.style.display = "inline-flex";
    bouton.style.alignItems = "center";
    bouton.style.cursor = "pointer";
    bouton.style.zIndex = "999999";
    bouton.style.opacity = "0.6";

    const conteneurIcone = document.createElement("span");
    conteneurIcone.style.position = "relative";
    conteneurIcone.style.display = "inline-flex";
    conteneurIcone.style.color = "#fff";
    conteneurIcone.style.filter = "drop-shadow(0 1px 3px rgba(0,0,0,0.9))";
    conteneurIcone.innerHTML =
      '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>';
    bouton.appendChild(conteneurIcone);

    const barre = document.createElement("span");
    barre.id = "cartometa-barre-bascule-auto-show";
    barre.style.position = "absolute";
    barre.style.left = "-2px";
    barre.style.top = "50%";
    barre.style.width = "calc(100% + 4px)";
    barre.style.height = "2px";
    barre.style.background = "#f95252";
    barre.style.transform = "translateY(-50%) rotate(-45deg)";
    barre.style.borderRadius = "1px";
    barre.style.pointerEvents = "none";
    conteneurIcone.appendChild(barre);

    bouton.addEventListener("mouseenter", () => (bouton.style.opacity = "1"));
    bouton.addEventListener("mouseleave", () => (bouton.style.opacity = "0.6"));
    bouton.addEventListener("click", () => {
      const actuels = obtenirParametres();
      actuels.apercuAutoParRound = !actuels.apercuAutoParRound;
      sauvegarderParametres(actuels);
      mettreAJourIconeBasculeAutoShow();
    });

    document.body.appendChild(bouton);
    mettreAJourIconeBasculeAutoShow();
  }

  function ajouterIconeParametres() {
    // Safety net: if adding this stylesheet fails for any reason (e.g.
    // document.head not ready yet if the script runs very early), this
    // must not block the rest of the routing (icons, round detection,
    // etc.) that runs right after in runOnGeoGuessr().
    try {
      ajouterStylesPanneauParametres();
    } catch (e) {
      console.log("[GeoGuessr→Cartometa] Non-blocking error while adding styles:", e);
    }

    if (document.getElementById("cartometa-icone-parametres")) return;

    const icone = document.createElement("div");
    icone.id = "cartometa-icone-parametres";
    icone.innerHTML =
      '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>';
    icone.style.color = "#fff";
    icone.style.filter = "drop-shadow(0 1px 3px rgba(0,0,0,0.9))";
    icone.title = "Cartometa settings";
    icone.style.position = "fixed";
    icone.style.display = "inline-flex";
    icone.style.bottom = "16px";
    icone.style.left = "16px";
    icone.style.cursor = "pointer";
    icone.style.zIndex = "999999";
    icone.style.opacity = "0.6";
    icone.addEventListener("mouseenter", () => (icone.style.opacity = "1"));
    icone.addEventListener("mouseleave", () => (icone.style.opacity = "0.6"));
    icone.addEventListener("click", ouvrirPanneauParametres);
    document.body.appendChild(icone);
  }

  // Some styles can't be set via element.style (inline CSS only) since
  // they target internal browser pseudo-elements (number input spinners,
  // color picker swatch): a real stylesheet is required. Injected once
  // per page.
  function ajouterStylesPanneauParametres() {
    if (document.getElementById("cartometa-styles-parametres")) return;

    const style = document.createElement("style");
    style.id = "cartometa-styles-parametres";
    style.textContent = `
      #cartometa-panneau-parametres input[type="number"] {
        -moz-appearance: textfield;
      }
      #cartometa-panneau-parametres input[type="number"]::-webkit-inner-spin-button,
      #cartometa-panneau-parametres input[type="number"]::-webkit-outer-spin-button {
        -webkit-appearance: none;
        margin: 0;
        background: transparent;
      }
      #cartometa-panneau-parametres input[type="color"] {
        -webkit-appearance: none;
        appearance: none;
        border: none;
        border-radius: 50%;
        overflow: hidden;
        padding: 0;
      }
      #cartometa-panneau-parametres input[type="color"]::-webkit-color-swatch-wrapper {
        padding: 0;
        border-radius: 50%;
      }
      #cartometa-panneau-parametres input[type="color"]::-webkit-color-swatch {
        border: none;
        border-radius: 50%;
      }
      #cartometa-panneau-parametres input[type="color"]::-moz-color-swatch {
        border: none;
        border-radius: 50%;
      }
      #cartometa-panneau-parametres input[type="range"] {
        -webkit-appearance: none;
        appearance: none;
        background: transparent;
        cursor: pointer;
        border: none;
        outline: none;
        padding: 0;
        margin: 0;
      }
      #cartometa-panneau-parametres input[type="range"]:focus {
        outline: none;
      }
      #cartometa-panneau-parametres .cartometa-champ-valeur-reglage {
        -moz-appearance: textfield;
      }
      #cartometa-panneau-parametres .cartometa-champ-valeur-reglage::-webkit-inner-spin-button,
      #cartometa-panneau-parametres .cartometa-champ-valeur-reglage::-webkit-outer-spin-button {
        -webkit-appearance: none;
        margin: 0;
      }
      #cartometa-panneau-parametres .cartometa-champ-valeur-reglage:hover,
      #cartometa-panneau-parametres .cartometa-champ-valeur-reglage:focus {
        border-color: rgba(255, 255, 255, 0.25);
        outline: none;
      }
      #cartometa-panneau-parametres input[type="range"]::-webkit-slider-runnable-track {
        height: 4px;
        border-radius: 2px;
        background: var(--curseur-couleur, #5EBF82);
        opacity: 0.4;
      }
      #cartometa-panneau-parametres input[type="range"]::-webkit-slider-thumb {
        -webkit-appearance: none;
        margin-top: -5px;
        width: 14px;
        height: 14px;
        border-radius: 50%;
        background: var(--curseur-couleur-clair, #8fdaad);
        border: none;
        cursor: pointer;
      }
      #cartometa-panneau-parametres input[type="range"]::-moz-range-track {
        height: 4px;
        border-radius: 2px;
        background: var(--curseur-couleur, #5EBF82);
        opacity: 0.4;
      }
      #cartometa-panneau-parametres input[type="range"]::-moz-range-thumb {
        width: 14px;
        height: 14px;
        border-radius: 50%;
        background: var(--curseur-couleur-clair, #8fdaad);
        border: none;
        cursor: pointer;
      }
    `;
    (document.head || document.documentElement).appendChild(style);
  }

  function ouvrirPanneauParametres() {
    if (document.getElementById("cartometa-panneau-parametres")) return;

    const parametres = obtenirParametres();

    const panneau = document.createElement("div");
    panneau.id = "cartometa-panneau-parametres";
    panneau.style.position = "fixed";
    panneau.style.bottom = "50px";
    panneau.style.left = "16px";
    panneau.style.background = "rgba(20,20,20,0.95)";
    panneau.style.borderRadius = "10px";
    panneau.style.padding = "14px";
    panneau.style.zIndex = "999999";
    panneau.style.fontFamily = "sans-serif";
    panneau.style.color = "#fff";
    panneau.style.boxShadow = "0 4px 16px rgba(0,0,0,0.5)";
    panneau.style.minWidth = "280px";

    const ligneTitre = document.createElement("div");
    ligneTitre.style.display = "flex";
    ligneTitre.style.justifyContent = "space-between";
    ligneTitre.style.alignItems = "center";
    ligneTitre.style.marginBottom = "16px";

    const titre = document.createElement("strong");
    titre.textContent = "Cartometa settings";
    titre.style.fontSize = "16px";
    ligneTitre.appendChild(titre);

    // Same small icon group as the metas carousel: FAQ/help, Discord,
    // then the reset button — grouped together on the right.
    const groupeIconesReglages = document.createElement("div");
    groupeIconesReglages.style.display = "flex";
    groupeIconesReglages.style.alignItems = "center";
    groupeIconesReglages.style.gap = "10px";
    groupeIconesReglages.style.marginLeft = "auto";

    const boutonFAQReglages = document.createElement("span");
    boutonFAQReglages.innerHTML =
      '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>';
    boutonFAQReglages.style.color = "#ccc";
    boutonFAQReglages.style.display = "inline-flex";
    boutonFAQReglages.title = "About Cartometa / FAQ";
    boutonFAQReglages.style.cursor = "pointer";
    boutonFAQReglages.style.opacity = "0.75";
    boutonFAQReglages.addEventListener("mouseenter", () => (boutonFAQReglages.style.opacity = "1"));
    boutonFAQReglages.addEventListener("mouseleave", () => (boutonFAQReglages.style.opacity = "0.75"));
    boutonFAQReglages.addEventListener("click", ouvrirFAQ);
    groupeIconesReglages.appendChild(boutonFAQReglages);

    const lienDiscordReglages = document.createElement("a");
    lienDiscordReglages.href = "https://discord.gg/xMZcwgc8nM";
    lienDiscordReglages.target = "_blank";
    lienDiscordReglages.rel = "noopener noreferrer";
    lienDiscordReglages.title = "Cartometa's Discord server";
    lienDiscordReglages.style.display = "inline-flex";
    lienDiscordReglages.style.color = "#fff";
    lienDiscordReglages.style.filter = "drop-shadow(0 1px 3px rgba(0,0,0,0.9))";
    lienDiscordReglages.style.opacity = "0.75";
    lienDiscordReglages.addEventListener("mouseenter", () => (lienDiscordReglages.style.opacity = "1"));
    lienDiscordReglages.addEventListener("mouseleave", () => (lienDiscordReglages.style.opacity = "0.75"));
    lienDiscordReglages.innerHTML =
      '<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M20.317 4.37a19.79 19.79 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028 14.09 14.09 0 0 0 1.226-1.994.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.3 12.3 0 0 1-1.873.893.076.076 0 0 0-.04.106c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.84 19.84 0 0 0 6.002-3.03.077.077 0 0 0 .032-.055c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.028zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.418 2.157-2.418 1.21 0 2.176 1.094 2.157 2.418 0 1.334-.955 2.419-2.157 2.419zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.418 2.157-2.418 1.21 0 2.176 1.094 2.157 2.418 0 1.334-.946 2.419-2.157 2.419z"/></svg>';
    groupeIconesReglages.appendChild(lienDiscordReglages);

    ligneTitre.appendChild(groupeIconesReglages);

    const boutonReinit = document.createElement("span");
    boutonReinit.innerHTML =
      '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>';
    boutonReinit.style.display = "inline-flex";
    boutonReinit.style.marginLeft = "10px";
    boutonReinit.style.color = "#ccc";
    boutonReinit.title = "Reset all settings to their default values";
    boutonReinit.style.cursor = "pointer";
    boutonReinit.style.opacity = "0.7";
    boutonReinit.addEventListener("mouseenter", () => (boutonReinit.style.opacity = "1"));
    boutonReinit.addEventListener("mouseleave", () => (boutonReinit.style.opacity = "0.7"));
    boutonReinit.addEventListener("click", () => {
      if (confirm("Reset all Cartometa settings to their default values?")) {
        sauvegarderParametres({ ...PARAMETRES_PAR_DEFAUT });
        panneau.remove();
        ouvrirPanneauParametres(); // rebuild the panel with the restored defaults
        mettreAJourIconeBasculeAutoShow();
      }
    });
    ligneTitre.appendChild(boutonReinit);

    panneau.appendChild(ligneTitre);

    // Link to Cartometa's homepage, highlighted with the user's chosen
    // accent color.
    const lienCartometa = document.createElement("a");
    lienCartometa.href = "https://cartometa.com";
    lienCartometa.target = "_blank";
    lienCartometa.rel = "noopener noreferrer";
    lienCartometa.textContent = "🌍 Open Cartometa.com";
    lienCartometa.style.display = "block";
    lienCartometa.style.textAlign = "center";
    lienCartometa.style.padding = "8px";
    lienCartometa.style.marginBottom = "14px";
    lienCartometa.style.borderRadius = "8px";
    lienCartometa.style.background = parametres.couleurAccent;
    lienCartometa.style.color = "#111";
    lienCartometa.style.fontWeight = "bold";
    lienCartometa.style.textDecoration = "none";
    lienCartometa.style.fontSize = "12px";
    lienCartometa.title = "Opens Cartometa's homepage in a new tab.";
    panneau.appendChild(lienCartometa);

    // Styled section title, with a horizontal separator filling the
    // remaining space to its right (line + text + line).
    function ajouterTitreSection(texte, premierBloc) {
      const ligneTitre = document.createElement("div");
      ligneTitre.style.display = "flex";
      ligneTitre.style.alignItems = "center";
      ligneTitre.style.gap = "8px";
      ligneTitre.style.margin = premierBloc ? "0 0 10px 0" : "18px 0 10px 0";

      const texteTitre = document.createElement("span");
      texteTitre.textContent = texte;
      texteTitre.style.fontSize = "12px";
      texteTitre.style.fontWeight = "bold";
      texteTitre.style.textTransform = "uppercase";
      texteTitre.style.letterSpacing = "0.5px";
      texteTitre.style.color = "#999";
      texteTitre.style.whiteSpace = "nowrap";
      ligneTitre.appendChild(texteTitre);

      const traitFin = document.createElement("div");
      traitFin.style.flex = "1";
      traitFin.style.borderTop = "1px solid #444";
      ligneTitre.appendChild(traitFin);

      panneau.appendChild(ligneTitre);
    }

    // Helper for numeric settings (zoom, width, metas count): a label
    // on the left, a slider on the right, with auto-save and min/max
    // bounds.
    function ajouterReglageNombre(libelle, cle, min, max, infobulle, suffixe) {
      const ligneReglage = document.createElement("div");
      ligneReglage.style.marginBottom = "6px";
      if (infobulle) ligneReglage.title = infobulle;

      const enTete = document.createElement("div");
      enTete.style.display = "flex";
      enTete.style.justifyContent = "space-between";
      enTete.style.fontSize = "12px";
      enTete.style.marginBottom = "1px";

      const label = document.createElement("span");
      label.textContent = libelle;
      enTete.appendChild(label);

      const zoneValeur = document.createElement("span");
      zoneValeur.style.display = "inline-flex";
      zoneValeur.style.alignItems = "baseline";
      zoneValeur.style.gap = "2px";
      enTete.appendChild(zoneValeur);

      const valeurAffichee = document.createElement("input");
      valeurAffichee.type = "number";
      valeurAffichee.min = min;
      valeurAffichee.max = max;
      valeurAffichee.value = parametres[cle];
      valeurAffichee.style.width = String(max).length * 8 + 12 + "px";
      valeurAffichee.style.color = parametres.couleurAccent;
      valeurAffichee.style.fontWeight = "bold";
      valeurAffichee.style.fontSize = "12px";
      valeurAffichee.style.textAlign = "right";
      valeurAffichee.style.background = "transparent";
      // As close to invisible as possible while still being clickable and
      // editable: no border/background at rest, just a very faint line
      // on hover/focus so it doesn't look like plain unclickable text.
      valeurAffichee.style.border = "1px solid transparent";
      valeurAffichee.style.borderRadius = "3px";
      valeurAffichee.style.padding = "0 2px";
      valeurAffichee.className = "cartometa-champ-valeur-reglage";
      zoneValeur.appendChild(valeurAffichee);

      if (suffixe) {
        const spanSuffixe = document.createElement("span");
        spanSuffixe.textContent = suffixe;
        spanSuffixe.style.color = parametres.couleurAccent;
        spanSuffixe.style.fontWeight = "bold";
        zoneValeur.appendChild(spanSuffixe);
      }

      ligneReglage.appendChild(enTete);

      const curseur = document.createElement("input");
      curseur.type = "range";
      curseur.min = min;
      curseur.max = max;
      curseur.value = parametres[cle];
      curseur.style.width = "100%";
      curseur.style.setProperty("--curseur-couleur", parametres.couleurAccent);
      curseur.style.setProperty("--curseur-couleur-clair", eclaircirCouleur(parametres.couleurAccent, 0.35));
      curseur.className = "cartometa-curseur-reglage"; // for live color updates

      function appliquerValeur(nouvelleValeur, sauvegarder) {
        nouvelleValeur = Math.min(max, Math.max(min, nouvelleValeur));
        curseur.value = nouvelleValeur;
        valeurAffichee.value = nouvelleValeur;
        if (sauvegarder) {
          const actuels = obtenirParametres();
          actuels[cle] = nouvelleValeur;
          sauvegarderParametres(actuels);
        }
      }

      // "input" fires continuously while dragging (smooth value display),
      // "change" only fires on release (that's when we save, to avoid
      // writing to localStorage on every pixel of slider movement).
      curseur.addEventListener("input", () => {
        valeurAffichee.value = curseur.value;
      });
      curseur.addEventListener("change", () => {
        const actuels = obtenirParametres();
        actuels[cle] = parseInt(curseur.value, 10);
        sauvegarderParametres(actuels);
      });

      // Typing directly into the number field keeps the slider in sync
      // live, and saves once the field loses focus or Enter is pressed
      // (not on every keystroke, same reasoning as the slider above).
      valeurAffichee.addEventListener("input", () => {
        if (valeurAffichee.value === "") return;
        curseur.value = valeurAffichee.value;
      });
      valeurAffichee.addEventListener("change", () => {
        const val = parseInt(valeurAffichee.value, 10);
        appliquerValeur(isNaN(val) ? parametres[cle] : val, true);
      });
      valeurAffichee.addEventListener("keydown", (e) => {
        if (e.key === "Enter") valeurAffichee.blur();
      });

      ligneReglage.appendChild(curseur);
      panneau.appendChild(ligneReglage);
    }

    // ---- Bloc 1 : Meta Carousel ----
    ajouterTitreSection("Meta Carousel", true);

    ajouterReglageNombre(
      "Preview window width (px)",
      "largeurFenetreApercu",
      300,
      1400,
      "Width of the metas preview window, in pixels."
    );
    ajouterReglageNombre(
      "Number of metas to load",
      "nombreMetas",
      1,
      20,
      "How many metas are fetched and shown per location (max 20)."
    );
    ajouterReglageNombre(
      "Meta polygon opacity",
      "opaciteSilhouette",
      0,
      80,
      "Fill opacity of the meta's polygon drawn on GeoGuessr's map. At 0%, only the outline is shown.",
      "%"
    );

    // ---- Bloc 2 : Cartometa options ----
    ajouterTitreSection("Cartometa options");

    ajouterReglageNombre(
      "Cartometa zoom level",
      "zoomCartometa",
      1,
      15,
      "Initial zoom level used when opening a location on Cartometa."
    );

    // ---- Bloc 3 : Script personalization ----
    ajouterTitreSection("Script personalization");

    const ligneCouleur = document.createElement("div");
    ligneCouleur.style.display = "flex";
    ligneCouleur.style.alignItems = "center";
    ligneCouleur.style.justifyContent = "space-between";
    ligneCouleur.style.gap = "10px";
    ligneCouleur.style.fontSize = "12px";
    ligneCouleur.title =
      "Accent color used for buttons, highlights and links throughout the script (on both GeoGuessr and Cartometa).";

    const labelCouleur = document.createElement("span");
    labelCouleur.textContent = "Accent color";
    ligneCouleur.appendChild(labelCouleur);

    const inputCouleur = document.createElement("input");
    inputCouleur.type = "color";
    inputCouleur.value = parametres.couleurAccent;
    inputCouleur.style.width = "28px";
    inputCouleur.style.height = "28px";
    inputCouleur.style.padding = "0";
    inputCouleur.style.border = "none";
    inputCouleur.style.cursor = "pointer";
    inputCouleur.addEventListener("input", () => {
      const actuels = obtenirParametres();
      actuels.couleurAccent = inputCouleur.value;
      sauvegarderParametres(actuels);
      lienCartometa.style.background = inputCouleur.value; // instant preview
      panneau.querySelectorAll(".cartometa-curseur-reglage").forEach((c) => {
        c.style.setProperty("--curseur-couleur", inputCouleur.value);
        c.style.setProperty("--curseur-couleur-clair", eclaircirCouleur(inputCouleur.value, 0.35));
      });
      panneau.querySelectorAll(".cartometa-champ-valeur-reglage").forEach((c) => {
        c.style.color = inputCouleur.value;
        if (c.nextSibling) c.nextSibling.style.color = inputCouleur.value; // the suffix span, if any
      });
    });
    ligneCouleur.appendChild(inputCouleur);
    panneau.appendChild(ligneCouleur);

    // Close on click outside the panel (but not on the icon itself,
    // otherwise clicking the icon would immediately reopen and close it).
    function fermerSiClicExterieur(e) {
      if (panneau.contains(e.target)) return;
      if (e.target.id === "cartometa-icone-parametres") return;
      panneau.remove();
      document.removeEventListener("click", fermerSiClicExterieur, true);
    }
    // setTimeout: avoids the click that just opened the panel (on the ⚙️
    // icon) from immediately triggering its own close.
    setTimeout(() => document.addEventListener("click", fermerSiClicExterieur, true), 0);

    document.body.appendChild(panneau);
  }

  // Builds the "batch" URL (all rounds): data is passed directly in the
  // URL hash (encoded), avoiding storage that would need extra
  // Tampermonkey permissions (GM_setValue/GM_getValue require a
  // re-authorization prompt at install time; if declined, it breaks the
  // ENTIRE script).
  function buildCartometaBatchUrl(rounds) {
    const parametres = obtenirParametres();
    const payload = {
      rounds,
      zoom: parametres.zoomCartometa,
      couleur: parametres.couleurAccent,
    };
    const encode = encodeURIComponent(JSON.stringify(payload));
    return `https://cartometa.com/#rounds=${encode}`;
  }

  // Builds the URL used for a background "preview": asks Cartometa to
  // auto-click the point AND return the metas found, instead of just
  // displaying the map.
  //
  // IMPORTANT: the hash stays in the STANDARD format (#lat,lng,zoom),
  // which the site knows how to read to center/zoom the map. A custom
  // hash format (tried early on, e.g. "#preview=...") isn't recognized
  // by their routing, leaving the map on a default point (observed: a
  // spot in the middle of the ocean), causing metas to never load. So
  // "preview" mode and the request id go through a separate query
  // parameter (?cartometaPreview=...) instead, which doesn't interfere
  // with the hash.
  function buildCartometaPreviewUrl(lat, lng, requestId) {
    const parametres = obtenirParametres();
    const latArrondi = lat.toFixed(4);
    const lngArrondi = lng.toFixed(4);
    return `https://cartometa.com/?cartometaPreview=${requestId}&metaCount=${parametres.nombreMetas}#${latArrondi},${lngArrondi},${parametres.zoomCartometa}`;
  }

  // ---------------------------------------------------------------
  // Metas preview directly inside GeoGuessr (background popup)
  // ---------------------------------------------------------------
  // Cartometa blocks iframe embedding (X-Frame-Options), so we use an
  // independent popup instead: it auto-clicks the point, grabs the
  // metas shown, sends them back via postMessage (the standard way to
  // communicate between two windows on different domains, which works
  // even when iframes are blocked), then closes itself.
  //
  // ⚠️ Known limitation: depending on the browser, this popup may
  // briefly flash on screen before closing — modern browsers restrict
  // how much control a script has over the position/size of a window
  // it opens.
  const requetesApercuEnCours = new Map(); // requestId -> callback function

  window.addEventListener("message", (event) => {
    if (event.origin !== "https://cartometa.com") return;
    if (!event.data || event.data.type !== "cartometa-metas") return;
    const rappel = requetesApercuEnCours.get(event.data.requestId);
    if (rappel) {
      rappel(event.data.metas);
      requetesApercuEnCours.delete(event.data.requestId);
    }
  });

  function demanderApercuMetas(lat, lng, rappel) {
    const requestId = "r" + Date.now() + Math.random().toString(36).slice(2);
    requetesApercuEnCours.set(requestId, rappel);

    // A blocked popup can show up differently depending on the browser:
    // window.open() returning null, throwing an exception, or returning
    // a valid window object that the browser then closes itself shortly
    // after (asynchronously). We cover all three cases rather than
    // relying only on "popup is null right after the call".
    let popup = null;
    try {
      popup = window.open(
        buildCartometaPreviewUrl(lat, lng, requestId),
        "cartometa-preview-" + requestId,
        "width=900,height=700,left=-2000,top=-2000"
      );
    } catch (e) {
      popup = null;
    }

    function signalerPopupBloquee() {
      console.log(
        "[GeoGuessr→Cartometa] The preview popup couldn't open (likely blocked by the browser)."
      );
      if (requetesApercuEnCours.has(requestId)) {
        requetesApercuEnCours.delete(requestId);
        rappel(null, "popup_bloquee");
      }
    }

    if (!popup) {
      signalerPopupBloquee();
      return;
    }
    console.log("[GeoGuessr→Cartometa] Preview popup opened, requestId:", requestId);

    // Delayed check: some browsers do return a valid window object
    // immediately, but silently close it themselves right after (no
    // error) — without this second check, this case would go unnoticed
    // and the user would be stuck on "Loading..." until the safety
    // timeout, never seeing the explanatory message.
    setTimeout(() => {
      try {
        if (popup.closed) {
          signalerPopupBloquee();
        }
      } catch (e) {
        // fine if we can't check
      }
    }, 300);

    // NOTE: we previously tried to make the popup more discreet (removing
    // its focus, giving it back to the GeoGuessr tab, moving it off
    // screen) — but this seemed to disrupt GeoGuessr's own score screen
    // (likely a focus/visibility event interfering with its rendering),
    // which triggered our own auto-close almost instantly. Removed for
    // reliability, at the cost of a bit less visual discretion.

    // Safety net: if nothing comes back after a delay (slow site, etc.),
    // notify the caller instead of leaving the preview window stuck on
    // "Loading..." forever.
    setTimeout(() => {
      if (requetesApercuEnCours.has(requestId)) {
        requetesApercuEnCours.delete(requestId);
        rappel(null, "timeout");
        try {
          if (popup && !popup.closed) popup.close();
        } catch (e) {
          // fine if we can't close the popup ourselves
        }
      }
    }, 7000);
  }

  // Creates the draggable metas preview window (empty shell showing a
  // loading state) and kicks off the data request. Reuses the same
  // drag-and-drop logic as the "all rounds" panel.

  // Remembers the metas preview window's last dragged position, so it
  // reopens where the user last left it rather than snapping back to
  // the default corner each time. Stored via localStorage (same
  // mechanism as every other setting), so it survives page reloads,
  // new game sessions, and even a fresh visit the next day — a plain
  // in-memory variable was tried first but didn't survive any of that,
  // which is exactly what was reported as not working.

  function ouvrirApercuMetas(lat, lng, estAuto) {
    // Only one preview window at a time, to keep things simple: replace
    // any existing one instead of stacking several.
    const existante = document.getElementById("cartometa-apercu-metas");
    if (existante) existante.remove();

    masquerIconeReouverture(); // reopening a window, this icon isn't needed anymore

    const fenetre = document.createElement("div");
    fenetre.id = "cartometa-apercu-metas";
    fenetre.style.position = "fixed";
    const positionMemorisee = obtenirParametres();
    if (positionMemorisee.positionApercuGauche !== null && positionMemorisee.positionApercuHaut !== null) {
      fenetre.style.left = positionMemorisee.positionApercuGauche + "px";
      fenetre.style.top = positionMemorisee.positionApercuHaut + "px";
    } else {
      fenetre.style.top = "80px";
      fenetre.style.right = "16px";
    }
    fenetre.style.width = obtenirParametres().largeurFenetreApercu + "px";
    fenetre.style.background = "rgba(20,20,20,0.95)";
    fenetre.style.borderRadius = "10px";
    fenetre.style.padding = "10px";
    fenetre.style.zIndex = "999999";
    fenetre.style.fontFamily = "sans-serif";
    fenetre.style.color = "#fff";
    fenetre.style.boxShadow = "0 4px 16px rgba(0,0,0,0.5)";

    // Centralized close handler, used by ALL close points (✕ button,
    // auto-close on next round, close on navigation). The 🖼️ reopen icon
    // only makes sense for the automatic between-rounds preview
    // (estAuto=true): on recap screens, a 🖼️ icon per round already sits
    // right next to the 🔎 link, so offering a second way to reopen (the
    // bottom-left icon) would be redundant and pointless.
    fenetre.fermerAvecMemoire = function () {
      if (estAuto) {
        dernierApercuFerme = { lat, lng };
        afficherIconeReouverture();
      }
      supprimerPolygoneDeLaCarte();
      fermerLoupeActive();
      fenetre.remove();
    };

    // GeoGuessr's Street View panorama is rendered in an iframe: if
    // keyboard focus stays there (likely right after playing a round),
    // key presses never reach our window (browser security restriction
    // for iframes). We make the window focusable and focus it to
    // reclaim keyboard input.
    fenetre.tabIndex = -1;
    fenetre.style.outline = "none"; // avoid the default blue focus outline

    const enTete = document.createElement("div");
    enTete.style.display = "flex";
    enTete.style.justifyContent = "space-between";
    enTete.style.alignItems = "center";
    enTete.style.marginBottom = "8px";
    enTete.style.cursor = "move";
    enTete.style.userSelect = "none";

    const titre = document.createElement("strong");
    titre.id = "cartometa-titre-apercu";
    titre.textContent = "Metas";
    titre.style.fontSize = "17px";
    enTete.appendChild(titre);

    // Small icon group on the right: FAQ/help, Discord, then close —
    // grouped together so their spacing reads as one unit.
    const groupeIcones = document.createElement("div");
    groupeIcones.style.display = "flex";
    groupeIcones.style.alignItems = "center";
    groupeIcones.style.gap = "10px";
    groupeIcones.style.marginLeft = "auto";

    const boutonFAQ = document.createElement("span");
    boutonFAQ.innerHTML =
      '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>';
    boutonFAQ.style.color = "#fff";
    boutonFAQ.style.filter = "drop-shadow(0 1px 3px rgba(0,0,0,0.9))";
    boutonFAQ.style.display = "inline-flex";
    boutonFAQ.title = "About Cartometa / FAQ";
    boutonFAQ.style.cursor = "pointer";
    boutonFAQ.style.opacity = "0.75";
    boutonFAQ.addEventListener("mouseenter", () => (boutonFAQ.style.opacity = "1"));
    boutonFAQ.addEventListener("mouseleave", () => (boutonFAQ.style.opacity = "0.75"));
    boutonFAQ.addEventListener("click", (e) => {
      e.stopPropagation(); // don't let this also start a header drag
      ouvrirFAQ();
    });
    groupeIcones.appendChild(boutonFAQ);

    const lienDiscord = document.createElement("a");
    lienDiscord.href = "https://discord.gg/xMZcwgc8nM";
    lienDiscord.target = "_blank";
    lienDiscord.rel = "noopener noreferrer";
    lienDiscord.title = "Cartometa's Discord server";
    lienDiscord.style.display = "inline-flex";
    lienDiscord.style.color = "#fff";
    lienDiscord.style.filter = "drop-shadow(0 1px 3px rgba(0,0,0,0.9))";
    lienDiscord.style.opacity = "0.75";
    lienDiscord.addEventListener("mouseenter", () => (lienDiscord.style.opacity = "1"));
    lienDiscord.addEventListener("mouseleave", () => (lienDiscord.style.opacity = "0.75"));
    lienDiscord.addEventListener("mousedown", (e) => e.stopPropagation()); // don't start a header drag
    lienDiscord.innerHTML =
      '<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M20.317 4.37a19.79 19.79 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028 14.09 14.09 0 0 0 1.226-1.994.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.3 12.3 0 0 1-1.873.893.076.076 0 0 0-.04.106c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.84 19.84 0 0 0 6.002-3.03.077.077 0 0 0 .032-.055c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.028zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.418 2.157-2.418 1.21 0 2.176 1.094 2.157 2.418 0 1.334-.955 2.419-2.157 2.419zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.418 2.157-2.418 1.21 0 2.176 1.094 2.157 2.418 0 1.334-.946 2.419-2.157 2.419z"/></svg>';
    groupeIcones.appendChild(lienDiscord);

    enTete.appendChild(groupeIcones);

    const fermer = document.createElement("span");
    fermer.innerHTML =
      '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
    fermer.style.display = "inline-flex";
    fermer.style.color = "#fff";
    fermer.style.filter = "drop-shadow(0 1px 3px rgba(0,0,0,0.9))";
    fermer.title = "Close";
    fermer.style.cursor = "pointer";
    fermer.style.marginLeft = "12px";
    fermer.style.opacity = "0.75";
    fermer.addEventListener("mouseenter", () => (fermer.style.opacity = "1"));
    fermer.addEventListener("mouseleave", () => (fermer.style.opacity = "0.75"));
    fermer.addEventListener("click", () => fenetre.fermerAvecMemoire());
    enTete.appendChild(fermer);

    fenetre.appendChild(enTete);

    // Drag on the header (same logic as the "all rounds" panel on
    // Cartometa), remembering the final position so the window reopens
    // there next time.
    let enTrainDeGlisser = false;
    let decalageX = 0;
    let decalageY = 0;

    enTete.addEventListener("mousedown", (e) => {
      enTrainDeGlisser = true;
      const rect = fenetre.getBoundingClientRect();
      decalageX = e.clientX - rect.left;
      decalageY = e.clientY - rect.top;
      fenetre.style.left = rect.left + "px";
      fenetre.style.top = rect.top + "px";
      fenetre.style.right = "auto";
      e.preventDefault();
    });
    document.addEventListener("mousemove", (e) => {
      if (!enTrainDeGlisser) return;
      fenetre.style.left = e.clientX - decalageX + "px";
      fenetre.style.top = e.clientY - decalageY + "px";
    });
    document.addEventListener("mouseup", () => {
      if (!enTrainDeGlisser) return;
      enTrainDeGlisser = false;
      const actuels = obtenirParametres();
      actuels.positionApercuGauche = parseInt(fenetre.style.left, 10);
      actuels.positionApercuHaut = parseInt(fenetre.style.top, 10);
      sauvegarderParametres(actuels);
    });

    const contenu = document.createElement("div");
    contenu.style.minHeight = "160px";
    contenu.style.display = "flex";
    contenu.style.alignItems = "center";
    contenu.style.justifyContent = "center";
    contenu.style.textAlign = "center";
    contenu.style.fontSize = "13px";
    contenu.style.color = "#ccc";
    contenu.textContent = "Loading metas...";
    fenetre.appendChild(contenu);

    document.body.appendChild(fenetre);
    fenetre.focus();

    // GeoGuessr is an SPA (see the icons/buttons section above): this
    // window must close itself as soon as the user navigates to another
    // page, rather than staying displayed forever. We watch the URL
    // rather than a mode-specific DOM element, since this window can be
    // opened from any of the 4 game modes.
    const cheminDepart = location.pathname;
    const intervalFermeture = setInterval(() => {
      if (!fenetre.isConnected) {
        clearInterval(intervalFermeture); // already closed manually
        return;
      }
      if (location.pathname !== cheminDepart) {
        supprimerPolygoneDeLaCarte();
        fermerLoupeActive();
        fenetre.remove();
        clearInterval(intervalFermeture);
      }
    }, 1000);

    demanderApercuMetas(lat, lng, (metas, raison) => {
      // The window may have been closed by the user in the meantime.
      if (!fenetre.isConnected) return;
      remplirApercuMetas(fenetre, contenu, lat, lng, metas, raison);
      // Initial focus may have been lost during the async wait (metas
      // loading): reclaim it here once content is actually shown.
      fenetre.focus();
    });

    return fenetre;
  }

  // Fills the preview window once metas are received: a carousel
  // showing one meta at a time (image + text), navigable via arrows AND
  // navigation dots at the bottom. The "More on Cartometa" button is NOT
  // a carousel slide: it's an always-visible button, at the
  // bottom-right of the navigation dots, so it stays accessible
  // regardless of which meta is shown.
  // Opens a meta's image full-screen in a simple lightbox overlay:
  // click anywhere (or press Escape) to close it.
  // Adds a classic "magnifier lens" hover effect on a small thumbnail
  // image: a circular lens follows the cursor while hovering, showing a
  // zoomed-in portion of the same image at that spot (common pattern on
  // product photos).
  // Shared reference (not scoped per-image) so the lens can be closed
  // from OUTSIDE this function too — needed because "mouseleave" only
  // fires if the mouse actually moves off the image; if the image
  // itself disappears out from under a still-hovering cursor instead
  // (switching metas, closing the preview, moving to the next round...),
  // no such event ever fires, and the lens would otherwise stay stuck
  // on screen forever — worse, a NEW one on top of it for every
  // subsequent meta, stacking up indefinitely.
  let loupeActive = null;

  function fermerLoupeActive() {
    if (loupeActive) {
      loupeActive.remove();
      loupeActive = null;
    }
  }

  // Tracks the currently active magnifier mousemove listener, so a new
  // one can explicitly replace it (see below) instead of relying only
  // on stale ones noticing they're outdated and self-removing — a gap
  // that let multiple listeners (from different, previously-viewed
  // slides) run at once, each checking its own old image's bounds
  // against the SAME live cursor position. That's what caused the
  // frozen-lens symptom: whichever stale listener happened to run last
  // for a given mousemove could overwrite what the current one had just
  // set, using coordinates that made no sense for the image actually on
  // screen.
  let gererMouvementLoupeActuel = null;

  function ajouterEffetLoupe(img, facteurZoom) {
    if (gererMouvementLoupeActuel) {
      document.removeEventListener("mousemove", gererMouvementLoupeActuel);
      gererMouvementLoupeActuel = null;
    }

    // Listening globally on `document`, not on the image or its
    // container: a neighboring element (carousel arrow, window header,
    // padding...) sitting close to the image's edge could otherwise
    // intercept mousemove before it bubbles up through the image's own
    // DOM branch. A document-level listener sidesteps that: it fires
    // for every mouse movement on the page regardless of which element
    // technically receives it, and we do our own bounds check against
    // the image's real screen position from raw cursor coordinates.
    function gererMouvement(e) {
      if (!img.isConnected) {
        // Belt and suspenders: this shouldn't normally still be
        // attached once its image is gone, since a newer call to
        // ajouterEffetLoupe already removes it explicitly above — but
        // if this is ever the very last one and no newer slide replaced
        // it, this self-removal still cleans it up.
        document.removeEventListener("mousemove", gererMouvement);
        if (gererMouvementLoupeActuel === gererMouvement) gererMouvementLoupeActuel = null;
        return;
      }

      const rect = img.getBoundingClientRect();
      const dansImage =
        e.clientX >= rect.left && e.clientX <= rect.right && e.clientY >= rect.top && e.clientY <= rect.bottom;

      if (!dansImage) {
        fermerLoupeActive();
        return;
      }

      if (!loupeActive) {
        loupeActive = document.createElement("div");
        loupeActive.style.position = "fixed";
        loupeActive.style.width = "160px";
        loupeActive.style.height = "160px";
        loupeActive.style.borderRadius = "50%";
        loupeActive.style.boxShadow = "0 4px 14px rgba(0,0,0,0.6)";
        loupeActive.style.pointerEvents = "none"; // never intercepts the mouse itself
        loupeActive.style.background = "#1c1c1c"; // shows through near any edge, where the lens legitimately extends past the image itself
        loupeActive.style.backgroundImage = `url(${img.src})`;
        loupeActive.style.backgroundRepeat = "no-repeat";
        loupeActive.style.zIndex = "1000001"; // above even the full-size viewer, just in case
        document.body.appendChild(loupeActive);
      }

      const xPourcent = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
      const yPourcent = Math.min(1, Math.max(0, (e.clientY - rect.top) / rect.height));

      const largeurFond = rect.width * facteurZoom;
      const hauteurFond = rect.height * facteurZoom;
      const rayon = 80; // half of the lens's 160px size

      // Near any edge, the lens legitimately shows a bit of "nothing"
      // past the image's own boundary — same as a real magnifying glass
      // held close to the edge of a photo. Earlier, that blank area
      // rendered as stark, undecorated blank space, which combined with
      // the border/edge geometry made the lens look stuck rather than
      // intentional. Giving loupeActive its own neutral background-color
      // (set once, at creation) makes that margin read as a deliberate
      // part of the effect on every edge, instead of a glitch on some
      // of them.
      const bx = rayon - xPourcent * largeurFond;
      const by = rayon - yPourcent * hauteurFond;

      loupeActive.style.backgroundSize = `${largeurFond}px ${hauteurFond}px`;
      loupeActive.style.backgroundPosition = `${bx}px ${by}px`;
      loupeActive.style.left = e.clientX - rayon + "px";
      loupeActive.style.top = e.clientY - rayon + "px";
    }

    gererMouvementLoupeActuel = gererMouvement;
    document.addEventListener("mousemove", gererMouvement);
  }

  // Simple FAQ / help overlay explaining the Cartometa project and what
  // this script does — static content, no external page needed.
  function ouvrirFAQ() {
    const existant = document.getElementById("cartometa-fenetre-faq");
    if (existant) {
      existant.remove();
      return;
    }

    const superposition = document.createElement("div");
    superposition.id = "cartometa-fenetre-faq";
    superposition.style.position = "fixed";
    superposition.style.top = "0";
    superposition.style.left = "0";
    superposition.style.width = "100vw";
    superposition.style.height = "100vh";
    superposition.style.background = "rgba(0,0,0,0.75)";
    superposition.style.display = "flex";
    superposition.style.alignItems = "center";
    superposition.style.justifyContent = "center";
    superposition.style.zIndex = "1000002"; // above every other window, including the full-size image viewer
    superposition.style.fontFamily = "sans-serif";

    const panneau = document.createElement("div");
    panneau.style.background = "#1a1a1a";
    panneau.style.color = "#fff";
    panneau.style.borderRadius = "10px";
    panneau.style.padding = "20px";
    panneau.style.width = "min(90vw, 480px)";
    panneau.style.maxHeight = "80vh";
    panneau.style.overflowY = "auto";
    panneau.style.boxShadow = "0 8px 32px rgba(0,0,0,0.6)";
    panneau.addEventListener("click", (e) => e.stopPropagation()); // clicking inside must not close it

    const enTete = document.createElement("div");
    enTete.style.display = "flex";
    enTete.style.justifyContent = "space-between";
    enTete.style.alignItems = "center";
    enTete.style.marginBottom = "12px";

    const titre = document.createElement("strong");
    titre.textContent = "FAQ";
    titre.style.fontSize = "17px";
    enTete.appendChild(titre);

    const fermer = document.createElement("span");
    fermer.textContent = "✕";
    fermer.title = "Close";
    fermer.style.cursor = "pointer";
    fermer.addEventListener("click", () => superposition.remove());
    enTete.appendChild(fermer);

    panneau.appendChild(enTete);

    const entrees = [
      {
        q: "What is Cartometa?",
        a: "Cartometa is a website created by @Smaguy and a community project aiming to bring together as many verified metas as possible, from a wide range of sources, in a single tool for GeoGuessr. Cartometa links each meta to a polygon showing the geographic area where it applies.",
      },
      {
        q: "What does the Cartometa extension for GeoGuessr do?",
        a: "The extension displays, directly within GeoGuessr, the metas listed on Cartometa for the points you've played.",
      },
      {
        q: "Who wrote the metas?",
        a: "Metas come from guides, documents, and various other sources. Sources are generally provided and clickable. Cartometa doesn't produce original research as such — it's an aggregator.",
      },
      {
        q: "A meta shows up, but I can't actually see it in my panorama.",
        a: "Cartometa lists the areas where you might encounter certain metas, but it can't guarantee that a given meta will be relevant to every single point within that area. So it's normal for some displayed metas not to seem useful for the exact point you're solving — but keep the information in mind, it will likely come in handy another time.",
      },
      {
        q: "The script doesn't start automatically as expected, or the icons aren't there at the end of the game.",
        a: "The extension supports the following modes: Classic games, Challenges, Duels, Party Duels, Team Duels, Party Team Duels, and Party Live Challenges. GeoGuessr's interface can sometimes not play well with the script, which may require refreshing the page (F5). If the script still doesn't work or you run into any issues, feel free to report it on Cartometa's Discord or by DM to @valp40.",
      },
      {
        q: "Can I customize the script?",
        a: "Yes — a number of settings are available. Click the ⚙️ icon in the bottom-left corner of the screen to open the settings menu.",
      },
      {
        q: "Can I turn off the automatic metas display between rounds without disabling the script entirely?",
        a: "Yes — the automatic preview can be switched on or off at any time by clicking the small image icon right next to the settings gear (⚙️), in the bottom-left corner of the screen.",
      },
      {
        q: "Is this cheating?",
        a: "The extension isn't designed to help you while you're actively playing — only to help you review and analyze your guesses after you've played. It's a learning tool, not a cheating tool.",
      },
      {
        q: "Can I contribute to the project by submitting metas or ideas?",
        a: "Absolutely. You can join Cartometa's Discord server, where you'll find all the information you need: https://discord.gg/xMZcwgc8nM",
      },
    ];

    entrees.forEach(({ q, a }) => {
      const blocQ = document.createElement("p");
      blocQ.textContent = q;
      blocQ.style.fontWeight = "bold";
      blocQ.style.fontSize = "14px";
      blocQ.style.marginTop = "14px";
      blocQ.style.marginBottom = "4px";
      panneau.appendChild(blocQ);

      const blocA = document.createElement("p");
      blocA.style.fontSize = "13px";
      blocA.style.lineHeight = "1.5";
      blocA.style.color = "#ccc";
      blocA.style.margin = "0";

      // Turns the Discord URL into a real clickable link, rest stays
      // as plain text.
      const morceaux = a.split(/(https:\/\/\S+)/g);
      morceaux.forEach((morceau) => {
        if (morceau.startsWith("https://")) {
          const lien = document.createElement("a");
          lien.href = morceau;
          lien.target = "_blank";
          lien.rel = "noopener noreferrer";
          lien.textContent = morceau;
          lien.style.color = obtenirParametres().couleurAccent;
          blocA.appendChild(lien);
        } else {
          blocA.appendChild(document.createTextNode(morceau));
        }
      });
      panneau.appendChild(blocA);
    });

    superposition.appendChild(panneau);
    superposition.addEventListener("click", () => superposition.remove());
    document.body.appendChild(superposition);

    function surEchap(e) {
      if (e.key === "Escape") {
        superposition.remove();
        document.removeEventListener("keydown", surEchap);
      }
    }
    document.addEventListener("keydown", surEchap);
  }

  function ouvrirImageEnGrand(urlImage) {
    const existant = document.getElementById("cartometa-image-plein-ecran");
    if (existant) existant.remove();

    const superposition = document.createElement("div");
    superposition.id = "cartometa-image-plein-ecran";
    superposition.style.position = "fixed";
    superposition.style.top = "0";
    superposition.style.left = "0";
    superposition.style.width = "100vw";
    superposition.style.height = "100vh";
    superposition.style.background = "rgba(0,0,0,0.85)";
    superposition.style.display = "flex";
    superposition.style.alignItems = "center";
    superposition.style.justifyContent = "center";
    superposition.style.zIndex = "1000000"; // above every other panel/window
    superposition.style.cursor = "zoom-out";

    const grandeImage = document.createElement("img");
    grandeImage.src = urlImage;
    grandeImage.style.maxWidth = "90vw";
    grandeImage.style.maxHeight = "90vh";
    grandeImage.style.borderRadius = "8px";
    grandeImage.style.boxShadow = "0 8px 32px rgba(0,0,0,0.6)";
    grandeImage.style.transition = "transform 0.05s linear";
    grandeImage.style.transformOrigin = "center center";
    superposition.appendChild(grandeImage);

    // Fixed position at the top of the screen, independent of the
    // image's own position/size: since zooming scales the image via a
    // CSS transform (which doesn't affect layout), a hint placed right
    // below the image wouldn't actually track its zoomed edge — simpler
    // and more reliable to just anchor it to the screen instead.
    const indication = document.createElement("span");
    indication.textContent = "Scroll to zoom";
    indication.style.position = "fixed";
    indication.style.top = "16px";
    indication.style.left = "50%";
    indication.style.transform = "translateX(-50%)";
    indication.style.color = "#ddd";
    indication.style.fontSize = "14px";
    indication.style.fontFamily = "sans-serif";
    indication.style.userSelect = "none";
    superposition.appendChild(indication);

    // Mouse wheel zoom, centered on the cursor position: scrolling up
    // zooms in around wherever the cursor is, scrolling down zooms back
    // out, clamped between 1x and 5x.
    let zoomActuel = 1;
    grandeImage.addEventListener(
      "wheel",
      (e) => {
        e.preventDefault();
        e.stopPropagation(); // don't let it also scroll the page behind the overlay

        const rect = grandeImage.getBoundingClientRect();
        const xPourcent = ((e.clientX - rect.left) / rect.width) * 100;
        const yPourcent = ((e.clientY - rect.top) / rect.height) * 100;
        grandeImage.style.transformOrigin = `${xPourcent}% ${yPourcent}%`;

        zoomActuel += e.deltaY < 0 ? 0.25 : -0.25;
        zoomActuel = Math.min(5, Math.max(1, zoomActuel));
        grandeImage.style.transform = `scale(${zoomActuel})`;
        grandeImage.style.cursor = zoomActuel > 1 ? "zoom-in" : "zoom-out";
      },
      { passive: false }
    );

    // Clicking the image itself only zooms it back out (if zoomed in),
    // rather than closing the whole viewer — avoids accidentally
    // closing while trying to inspect a zoomed-in detail. Clicking
    // anywhere OUTSIDE the image (the dark background) still closes it.
    grandeImage.addEventListener("click", (e) => {
      e.stopPropagation();
      if (zoomActuel > 1) {
        zoomActuel = 1;
        grandeImage.style.transform = "scale(1)";
        grandeImage.style.cursor = "zoom-out";
      }
    });

    function fermer() {
      superposition.remove();
      document.removeEventListener("keydown", surEchap);
    }
    function surEchap(e) {
      if (e.key === "Escape") fermer();
    }

    superposition.addEventListener("click", fermer);
    document.addEventListener("keydown", surEchap);

    document.body.appendChild(superposition);
  }

  // Converts a 2-letter ISO country code into its flag emoji. Purely
  // formulaic (each letter maps to a "regional indicator" Unicode
  // symbol) — no lookup table or external data needed for this part.
  // Static ISO 3166-1 alpha-2 -> English country name lookup. Purely
  // local data, no external service needed.
  const NOMS_PAYS = {
    AF: "Afghanistan",
    AL: "Albania",
    DZ: "Algeria",
    AS: "American Samoa",
    AD: "Andorra",
    AO: "Angola",
    AI: "Anguilla",
    AQ: "Antarctica",
    AG: "Antigua and Barbuda",
    AR: "Argentina",
    AM: "Armenia",
    AW: "Aruba",
    AU: "Australia",
    AT: "Austria",
    AZ: "Azerbaijan",
    BS: "Bahamas",
    BH: "Bahrain",
    BD: "Bangladesh",
    BB: "Barbados",
    BY: "Belarus",
    BE: "Belgium",
    BZ: "Belize",
    BJ: "Benin",
    BM: "Bermuda",
    BT: "Bhutan",
    BO: "Bolivia",
    BA: "Bosnia and Herzegovina",
    BW: "Botswana",
    BR: "Brazil",
    BN: "Brunei",
    BG: "Bulgaria",
    BF: "Burkina Faso",
    BI: "Burundi",
    KH: "Cambodia",
    CM: "Cameroon",
    CA: "Canada",
    CV: "Cabo Verde",
    KY: "Cayman Islands",
    CF: "Central African Republic",
    TD: "Chad",
    CL: "Chile",
    CN: "China",
    CO: "Colombia",
    KM: "Comoros",
    CG: "Congo",
    CD: "DR Congo",
    CR: "Costa Rica",
    CI: "Ivory Coast",
    HR: "Croatia",
    CU: "Cuba",
    CW: "Curacao",
    CY: "Cyprus",
    CZ: "Czechia",
    DK: "Denmark",
    DJ: "Djibouti",
    DM: "Dominica",
    DO: "Dominican Republic",
    EC: "Ecuador",
    EG: "Egypt",
    SV: "El Salvador",
    GQ: "Equatorial Guinea",
    ER: "Eritrea",
    EE: "Estonia",
    SZ: "Eswatini",
    ET: "Ethiopia",
    FK: "Falkland Islands",
    FO: "Faroe Islands",
    FJ: "Fiji",
    FI: "Finland",
    FR: "France",
    GF: "French Guiana",
    PF: "French Polynesia",
    GA: "Gabon",
    GM: "Gambia",
    GE: "Georgia",
    DE: "Germany",
    GH: "Ghana",
    GI: "Gibraltar",
    GR: "Greece",
    GL: "Greenland",
    GD: "Grenada",
    GP: "Guadeloupe",
    GU: "Guam",
    GT: "Guatemala",
    GG: "Guernsey",
    GN: "Guinea",
    GW: "Guinea-Bissau",
    GY: "Guyana",
    HT: "Haiti",
    HN: "Honduras",
    HK: "Hong Kong",
    HU: "Hungary",
    IS: "Iceland",
    IN: "India",
    ID: "Indonesia",
    IR: "Iran",
    IQ: "Iraq",
    IE: "Ireland",
    IM: "Isle of Man",
    IL: "Israel",
    IT: "Italy",
    JM: "Jamaica",
    JP: "Japan",
    JE: "Jersey",
    JO: "Jordan",
    KZ: "Kazakhstan",
    KE: "Kenya",
    KI: "Kiribati",
    KW: "Kuwait",
    KG: "Kyrgyzstan",
    LA: "Laos",
    LV: "Latvia",
    LB: "Lebanon",
    LS: "Lesotho",
    LR: "Liberia",
    LY: "Libya",
    LI: "Liechtenstein",
    LT: "Lithuania",
    LU: "Luxembourg",
    MO: "Macao",
    MG: "Madagascar",
    MW: "Malawi",
    MY: "Malaysia",
    MV: "Maldives",
    ML: "Mali",
    MT: "Malta",
    MH: "Marshall Islands",
    MQ: "Martinique",
    MR: "Mauritania",
    MU: "Mauritius",
    MX: "Mexico",
    FM: "Micronesia",
    MD: "Moldova",
    MC: "Monaco",
    MN: "Mongolia",
    ME: "Montenegro",
    MS: "Montserrat",
    MA: "Morocco",
    MZ: "Mozambique",
    MM: "Myanmar",
    NA: "Namibia",
    NR: "Nauru",
    NP: "Nepal",
    NL: "Netherlands",
    NC: "New Caledonia",
    NZ: "New Zealand",
    NI: "Nicaragua",
    NE: "Niger",
    NG: "Nigeria",
    NU: "Niue",
    MK: "North Macedonia",
    MP: "Northern Mariana Islands",
    NO: "Norway",
    OM: "Oman",
    PK: "Pakistan",
    PW: "Palau",
    PS: "Palestine",
    PA: "Panama",
    PG: "Papua New Guinea",
    PY: "Paraguay",
    PE: "Peru",
    PH: "Philippines",
    PN: "Pitcairn Islands",
    PL: "Poland",
    PT: "Portugal",
    PR: "Puerto Rico",
    QA: "Qatar",
    RE: "Reunion",
    RO: "Romania",
    RU: "Russia",
    RW: "Rwanda",
    BL: "Saint Barthelemy",
    KN: "Saint Kitts and Nevis",
    LC: "Saint Lucia",
    MF: "Saint Martin",
    PM: "Saint Pierre and Miquelon",
    VC: "Saint Vincent and the Grenadines",
    WS: "Samoa",
    SM: "San Marino",
    ST: "Sao Tome and Principe",
    SA: "Saudi Arabia",
    SN: "Senegal",
    RS: "Serbia",
    SC: "Seychelles",
    SL: "Sierra Leone",
    SG: "Singapore",
    SX: "Sint Maarten",
    SK: "Slovakia",
    SI: "Slovenia",
    SB: "Solomon Islands",
    SO: "Somalia",
    ZA: "South Africa",
    GS: "South Georgia",
    KR: "South Korea",
    SS: "South Sudan",
    ES: "Spain",
    LK: "Sri Lanka",
    SD: "Sudan",
    SR: "Suriname",
    SJ: "Svalbard",
    SE: "Sweden",
    CH: "Switzerland",
    SY: "Syria",
    TW: "Taiwan",
    TJ: "Tajikistan",
    TZ: "Tanzania",
    TH: "Thailand",
    TL: "Timor-Leste",
    TG: "Togo",
    TK: "Tokelau",
    TO: "Tonga",
    TT: "Trinidad and Tobago",
    TN: "Tunisia",
    TR: "Turkey",
    TM: "Turkmenistan",
    TC: "Turks and Caicos Islands",
    TV: "Tuvalu",
    UG: "Uganda",
    UA: "Ukraine",
    AE: "United Arab Emirates",
    GB: "United Kingdom",
    US: "United States",
    UY: "Uruguay",
    UZ: "Uzbekistan",
    VU: "Vanuatu",
    VA: "Vatican City",
    VE: "Venezuela",
    VN: "Vietnam",
    VG: "British Virgin Islands",
    VI: "U.S. Virgin Islands",
    WF: "Wallis and Futuna",
    EH: "Western Sahara",
    YE: "Yemen",
    ZM: "Zambia",
    ZW: "Zimbabwe",
    AX: "Aland Islands",
    XK: "Kosovo",
  };

  // Flag as a real image instead of an emoji: emoji flags rely on the
  // operating system shipping the right glyphs, and Windows notably
  // does not — Chrome on Windows falls back to showing the raw two
  // letters (e.g. "FR") instead of an actual flag. A small image from a
  // dedicated flag CDN renders identically everywhere.
  function urlDrapeau(code) {
    if (!code || code.length !== 2) return null;
    return `https://flagcdn.com/24x18/${code.toLowerCase()}.png`;
  }

  // Subdivision (state/province/region) via Nominatim's free reverse
  // geocoding — Cartometa doesn't expose this itself (confirmed), and
  // Google's Geocoding API would bill GeoGuessr's own quota for an
  // unauthorized use (same reasoning as the Street View panorama
  // feature we deliberately dropped earlier). This mirrors what popular
  // GeoGuessr scripts (e.g. miraclewhips' State Streak) already do
  // client-side, and is called far less often here (once per point the
  // user opens, versus their once-per-round automatic double query).
  //
  // Cached by rounded coordinates, so reopening the same point (e.g.
  // via the 🖼️ reopen icon) doesn't re-query it.
  const cacheSousDivisions = new Map();

  async function recupererSousDivision(lat, lng) {
    const cle = `${lat.toFixed(3)},${lng.toFixed(3)}`;
    if (cacheSousDivisions.has(cle)) return cacheSousDivisions.get(cle);

    let resultat = null;
    try {
      const url = `https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lng}&zoom=10&format=jsonv2`;
      const reponse = await fetch(url, { headers: { "Accept-Language": "en" } });
      const donnees = await reponse.json();
      const adresse = donnees && donnees.address;
      if (adresse) {
        // Field name varies a lot by country in Nominatim's data — try
        // the most common ones, in order of how specific/useful they
        // tend to be for this purpose.
        const champsPossibles = ["state", "region", "province", "state_district"];
        for (const champ of champsPossibles) {
          if (adresse[champ]) {
            resultat = adresse[champ];
            break;
          }
        }
      }
    } catch (e) {
      console.log("[GeoGuessr→Cartometa] Nominatim reverse geocoding failed:", e);
    }

    cacheSousDivisions.set(cle, resultat);
    return resultat;
  }

  function remplirApercuMetas(fenetre, contenu, lat, lng, metas, raison) {
    if (!metas || metas.length === 0) {
      contenu.style.display = "block";
      contenu.style.color = "#f7c5c5";
      contenu.textContent = "";

      if (raison === "popup_bloquee") {
        const p1 = document.createElement("p");
        p1.textContent = "Your browser blocked the popup needed to fetch metas.";
        p1.style.marginBottom = "8px";
        contenu.appendChild(p1);

        const p2 = document.createElement("p");
        p2.textContent = "To allow it (Chrome/Edge):";
        p2.style.fontSize = "12px";
        p2.style.color = "#ccc";
        p2.style.marginBottom = "4px";
        contenu.appendChild(p2);

        const etapes = document.createElement("ol");
        etapes.style.fontSize = "12px";
        etapes.style.color = "#ccc";
        etapes.style.textAlign = "left";
        etapes.style.margin = "0 auto";
        etapes.style.paddingLeft = "18px";
        etapes.style.maxWidth = "220px";
        [
          "Click the icon left of the address bar (lock or site info icon)",
          'Open "Site settings"',
          'Find "Pop-ups and redirects"',
          'Set it to "Allow"',
          "Reload this GeoGuessr page",
        ].forEach((texte) => {
          const li = document.createElement("li");
          li.textContent = texte;
          li.style.marginBottom = "2px";
          etapes.appendChild(li);
        });
        contenu.appendChild(etapes);
      } else {
        contenu.textContent = "Unable to load metas (timed out or none found).";
      }
      return;
    }

    contenu.textContent = "";
    contenu.style.display = "block";
    contenu.style.minHeight = "";

    const couleurAccent = obtenirParametres().couleurAccent;
    let indexActuel = 0;
    let filtreCategorie = null; // null = "All" (no filter)
    let sousDivisionActuelle = null; // filled in asynchronously below, once (not per meta — all metas here share the same point)

    function indicesVisibles() {
      const visibles = metas
        .map((_, i) => i)
        .filter((i) => !filtreCategorie || (metas[i].categorie || "").toLowerCase() === filtreCategorie);
      // Never filter down to nothing — if every remaining meta somehow
      // fails to match (shouldn't normally happen), fall back to
      // showing everything rather than an empty carousel.
      return visibles.length > 0 ? visibles : metas.map((_, i) => i);
    }

    // Subdivision (state/province/region) via Nominatim reverse
    // geocoding: this info isn't available from Cartometa's own data
    // (confirmed earlier), and Google's Geocoding API would bill
    // GeoGuessr's own quota for something they didn't authorize — so we
    // use Nominatim/OpenStreetMap instead (free, no key). One request
    // per opened point (not per meta), cached so revisiting the same
    // point doesn't re-query it.
    recupererSousDivision(lat, lng).then((sousDivision) => {
      sousDivisionActuelle = sousDivision;
      if (fenetre.isConnected) mettreAJourTitre();
    });

    // Category filter buttons — one per unique category present among
    // this point's metas, plus "All". Only shown when there's actually
    // more than one category to choose from (no point cluttering the UI
    // with a single, redundant option).
    const categoriesUniques = [...new Set(metas.map((m) => m.categorie).filter(Boolean))];
    const boutonsFiltre = [];

    function mettreAJourBoutonsFiltre() {
      boutonsFiltre.forEach(({ el, valeur }) => {
        const actif = valeur === filtreCategorie;
        el.style.background = actif ? couleurAccent : "transparent";
        el.style.color = actif ? "#111" : "#ccc";
        el.style.borderColor = actif ? couleurAccent : "rgba(255,255,255,0.25)";
        el.style.fontWeight = actif ? "bold" : "normal";
      });
    }

    if (categoriesUniques.length > 1) {
      const separateur = document.createElement("hr");
      separateur.style.border = "none";
      separateur.style.borderTop = "1px solid rgba(255,255,255,0.1)";
      separateur.style.margin = "8px 0 12px 0";
      contenu.appendChild(separateur);

      const ligneFiltres = document.createElement("div");
      ligneFiltres.style.display = "flex";
      ligneFiltres.style.flexWrap = "wrap";
      ligneFiltres.style.gap = "8px";
      ligneFiltres.style.marginBottom = "14px";
      contenu.appendChild(ligneFiltres);

      function creerBoutonFiltre(libelle, valeur) {
        const bouton = document.createElement("button");
        bouton.textContent = libelle;
        bouton.style.padding = "3px 10px";
        bouton.style.borderRadius = "12px";
        bouton.style.border = "1px solid rgba(255,255,255,0.25)";
        bouton.style.background = "transparent";
        bouton.style.color = "#ccc";
        bouton.style.fontSize = "13px";
        bouton.style.cursor = "pointer";
        bouton.style.textTransform = "capitalize";
        bouton.addEventListener("click", () => {
          filtreCategorie = valeur;
          mettreAJourBoutonsFiltre();
          construirePagination();
          afficherSlide(indexActuel); // snaps to the nearest meta still matching the new filter
        });
        ligneFiltres.appendChild(bouton);
        boutonsFiltre.push({ el: bouton, valeur });
      }

      creerBoutonFiltre("All", null);
      categoriesUniques.forEach((cat) => creerBoutonFiltre(cat, cat.toLowerCase()));
      mettreAJourBoutonsFiltre();
    }

    // Carousel row: left arrow, meta in the center, right arrow.
    const ligneCarrousel = document.createElement("div");
    ligneCarrousel.style.display = "flex";
    ligneCarrousel.style.alignItems = "center";
    ligneCarrousel.style.gap = "8px";
    contenu.appendChild(ligneCarrousel);

    function creerFleche(symbole) {
      const fleche = document.createElement("button");
      fleche.textContent = symbole;
      fleche.style.background = "transparent";
      fleche.style.color = "#fff";
      fleche.style.filter = "drop-shadow(0 1px 3px rgba(0,0,0,0.9))";
      fleche.style.border = "none";
      fleche.style.borderRadius = "6px";
      fleche.style.width = "28px";
      fleche.style.flexShrink = "0";
      fleche.style.alignSelf = "stretch"; // fills the row's full height (matches the image/text zone, excluding the header and bottom bar which sit outside this row)
      fleche.style.display = "flex";
      fleche.style.alignItems = "center";
      fleche.style.justifyContent = "center";
      fleche.style.cursor = "pointer";
      fleche.style.fontSize = "20px";
      fleche.addEventListener("mouseenter", () => {
        fleche.style.background = "rgba(255,255,255,0.08)";
      });
      fleche.addEventListener("mouseleave", () => {
        fleche.style.background = "transparent";
      });
      return fleche;
    }

    const flecheGauche = creerFleche("‹");
    const flecheDroite = creerFleche("›");
    flecheGauche.addEventListener("click", () => {
      const visibles = indicesVisibles();
      const pos = visibles.indexOf(indexActuel);
      afficherSlide(visibles[Math.max(0, pos - 1)]);
    });
    flecheDroite.addEventListener("click", () => {
      const visibles = indicesVisibles();
      const pos = visibles.indexOf(indexActuel);
      afficherSlide(visibles[Math.min(visibles.length - 1, pos + 1)]);
    });

    const zoneMeta = document.createElement("div");
    zoneMeta.style.flex = "1";
    zoneMeta.style.minWidth = "0"; // prevents the image from overflowing the flex layout
    zoneMeta.style.transition = "opacity 0.15s ease";

    ligneCarrousel.appendChild(flecheGauche);
    ligneCarrousel.appendChild(zoneMeta);
    ligneCarrousel.appendChild(flecheDroite);

    // Bottom bar: navigation dots on the left, Cartometa button on the
    // right, always shown together.
    const barreBas = document.createElement("div");
    barreBas.style.display = "flex";
    barreBas.style.alignItems = "center";
    barreBas.style.justifyContent = "space-between";
    barreBas.style.gap = "10px";
    barreBas.style.marginTop = "12px";
    fenetre.appendChild(barreBas);

    const pagination = document.createElement("div");
    pagination.style.display = "flex";
    pagination.style.alignItems = "center";
    pagination.style.gap = "6px";
    barreBas.appendChild(pagination);

    let libellePagination = null;

    function construirePagination() {
      pagination.textContent = "";
      libellePagination = document.createElement("span");
      libellePagination.style.fontSize = "13px";
      libellePagination.style.color = "#aaa";
      pagination.appendChild(libellePagination);
    }
    construirePagination();

    const boutonPlus = document.createElement("button");
    boutonPlus.textContent = "More on Cartometa";
    boutonPlus.style.padding = "8px 14px";
    boutonPlus.style.background = couleurAccent;
    boutonPlus.style.color = "#111";
    boutonPlus.style.fontWeight = "bold";
    boutonPlus.style.border = "none";
    boutonPlus.style.borderRadius = "6px";
    boutonPlus.style.cursor = "pointer";
    boutonPlus.style.fontSize = "13px";
    boutonPlus.style.flexShrink = "0";
    boutonPlus.addEventListener("click", () => {
      window.open(buildCartometaUrl(lat, lng), "_blank");
    });
    barreBas.appendChild(boutonPlus);

    // Replaces the generic "Metas" title with the flag + country name
    // (+ subdivision, once Nominatim has answered) for whichever meta
    // is currently shown, falling back to the generic title if this
    // particular meta has no country code.
    function mettreAJourTitre() {
      const meta = metas[indexActuel];
      const titreEl = document.getElementById("cartometa-titre-apercu");
      if (!titreEl) return;

      titreEl.textContent = "";
      if (meta.codePays) {
        const urlImgDrapeau = urlDrapeau(meta.codePays);
        if (urlImgDrapeau) {
          const imgDrapeau = document.createElement("img");
          imgDrapeau.src = urlImgDrapeau;
          imgDrapeau.alt = meta.codePays;
          imgDrapeau.style.width = "20px";
          imgDrapeau.style.verticalAlign = "middle";
          imgDrapeau.style.marginRight = "6px";
          imgDrapeau.style.borderRadius = "2px";
          titreEl.appendChild(imgDrapeau);
        }
        let texteTitre = NOMS_PAYS[meta.codePays.toUpperCase()] || meta.codePays;
        if (sousDivisionActuelle) texteTitre += ` - ${sousDivisionActuelle}`;
        titreEl.appendChild(document.createTextNode(texteTitre));
      } else {
        titreEl.textContent = "Metas";
      }
    }

    function afficherSlide(index) {
      // Clamp within the raw range first...
      if (index < 0) index = 0;
      if (index > metas.length - 1) index = metas.length - 1;

      // ...then, if the target doesn't match the active filter (e.g. the
      // filter was just changed and the previous meta no longer
      // qualifies), snap to whichever visible meta is closest to it,
      // rather than jumping to an arbitrary one.
      const visibles = indicesVisibles();
      if (!visibles.includes(index)) {
        index = visibles.reduce((meilleur, i) =>
          Math.abs(i - index) < Math.abs(meilleur - index) ? i : meilleur, visibles[0]);
      }
      indexActuel = index;

      const position = visibles.indexOf(index);
      libellePagination.textContent = `${position + 1} / ${visibles.length}`;
      flecheGauche.style.visibility = position === 0 ? "hidden" : "visible";
      flecheDroite.style.visibility = position === visibles.length - 1 ? "hidden" : "visible";

      zoneMeta.style.opacity = "0";
      zoneMeta.textContent = "";
      fermerLoupeActive(); // the previous slide's image is about to disappear; the lens must go with it

      const meta = metas[index];
      afficherPolygoneSurCarte(meta.geometrie);

      mettreAJourTitre();

      if (meta.image) {
        const conteneurImage = document.createElement("div");
        conteneurImage.style.position = "relative";
        conteneurImage.style.background = "#1c1c1c";
        conteneurImage.style.borderRadius = "8px";
        conteneurImage.style.padding = "8px";

        const img = document.createElement("img");
        img.src = meta.image;
        img.style.width = "100%";
        img.style.borderRadius = "4px";
        img.style.display = "block";
        conteneurImage.appendChild(img);
        ajouterEffetLoupe(img, 1.8);

        const boutonAgrandir = document.createElement("div");
        boutonAgrandir.innerHTML =
          '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>';
        boutonAgrandir.title = "View full size";
        boutonAgrandir.style.position = "absolute";
        boutonAgrandir.style.bottom = "14px";
        boutonAgrandir.style.right = "14px";
        boutonAgrandir.style.display = "flex";
        boutonAgrandir.style.alignItems = "center";
        boutonAgrandir.style.justifyContent = "center";
        boutonAgrandir.style.width = "26px";
        boutonAgrandir.style.height = "26px";
        boutonAgrandir.style.borderRadius = "50%";
        boutonAgrandir.style.background = "rgba(0,0,0,0.6)";
        boutonAgrandir.style.color = "#fff";
        boutonAgrandir.style.filter = "drop-shadow(0 1px 3px rgba(0,0,0,0.9))";
        boutonAgrandir.style.cursor = "zoom-in";
        boutonAgrandir.addEventListener("click", () => ouvrirImageEnGrand(meta.image));
        conteneurImage.appendChild(boutonAgrandir);

        zoneMeta.appendChild(conteneurImage);
      }

      const texte = document.createElement("p");
      texte.textContent = meta.texte || "";
      texte.style.fontSize = "15px";
      texte.style.marginTop = "10px";
      texte.style.lineHeight = "1.5";
      zoneMeta.appendChild(texte);

      if (meta.sourceUrl) {
        const lienSource = document.createElement("a");
        lienSource.href = meta.sourceUrl;
        lienSource.target = "_blank";
        lienSource.rel = "noopener noreferrer";
        lienSource.textContent = "Source";
        lienSource.style.display = "inline-block";
        lienSource.style.fontSize = "12px";
        lienSource.style.marginTop = "6px";
        lienSource.style.color = couleurAccent;
        zoneMeta.appendChild(lienSource);
      }

      // Fades the new content in: opacity was set to 0 right before
      // rebuilding zoneMeta above, so this transition (set on zoneMeta
      // itself) now animates it back to fully visible.
      requestAnimationFrame(() => {
        zoneMeta.style.opacity = "1";
      });
    }

    afficherSlide(0);

    // Keyboard navigation (left/right arrows), in addition to the
    // clickable arrows and dots. The listener removes itself once the
    // window is no longer shown (closed manually, or auto-closed on the
    // next round).
    function gestionClavier(e) {
      if (!fenetre.isConnected) {
        document.removeEventListener("keydown", gestionClavier);
        return;
      }
      if (e.key === "ArrowLeft") {
        afficherSlide(indexActuel - 1);
      } else if (e.key === "ArrowRight") {
        afficherSlide(indexActuel + 1);
      }
    }
    document.addEventListener("keydown", gestionClavier);
  }

  // Adds an "image" icon right after an existing icon (the 🔎 for each
  // round), to open the metas preview for that point. Shared across all
  // 4 game modes.
  function ajouterIconeApercu(lienVoisin, lat, lng, taille) {
    taille = taille || 19;
    const icone = document.createElement("a");
    icone.href = "javascript:void(0)";
    icone.innerHTML = `<svg width="${taille}" height="${taille}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>`;
    icone.style.color = "#fff";
    icone.style.filter = "drop-shadow(0 1px 3px rgba(0,0,0,0.9))";
    icone.title = "Cartometa metas preview";
    icone.style.position = "fixed";
    icone.style.display = "inline-flex";
    icone.style.transform = "translateY(-50%)";
    icone.style.textDecoration = "none";
    icone.style.cursor = "pointer";
    icone.style.zIndex = "999999";
    icone.style.pointerEvents = "auto";
    icone.addEventListener("click", (e) => {
      e.preventDefault();
      ouvrirApercuMetas(lat, lng);
    });
    document.body.appendChild(icone);

    function positionner() {
      const rect = lienVoisin.getBoundingClientRect();
      icone.style.top = rect.top + rect.height / 2 + "px";
      icone.style.left = rect.right + 4 + "px";
    }
    positionner();
    window.addEventListener("resize", positionner);
    window.addEventListener("scroll", positionner, true);

    return icone;
  }

  // Adds a "panel" icon (📋) anchored to a specific DOM element (e.g.
  // the "Total" row), which opens a new Cartometa tab listing all
  // rounds of the game as buttons.
  function ajouterBoutonTousLesRounds(ancre, rounds, id, taille) {
    if (!rounds || rounds.length === 0) return;
    if (ancre.dataset.cartometaFinalInjected) return;
    ancre.dataset.cartometaFinalInjected = "true";

    taille = taille || 21;
    const bouton = document.createElement("div");
    if (id) bouton.id = id;
    bouton.innerHTML = `<svg width="${taille}" height="${taille}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="3" width="16" height="18" rx="2"/><line x1="8" y1="8" x2="16" y2="8"/><line x1="8" y1="12" x2="16" y2="12"/><line x1="8" y1="16" x2="13" y2="16"/></svg>`;
    bouton.style.color = "#fff";
    bouton.style.filter = "drop-shadow(0 1px 3px rgba(0,0,0,0.9))";
    bouton.title = "View all rounds on Cartometa";
    bouton.style.position = "fixed";
    bouton.style.display = "inline-flex";
    bouton.style.transform = "translateY(-50%)";
    bouton.style.cursor = "pointer";
    bouton.style.zIndex = "999999";
    bouton.style.pointerEvents = "auto";
    document.body.appendChild(bouton);

    function positionner() {
      let rect;
      if (ancre.children.length === 0) {
        // "Simple" anchor (just text, like "Total" in Challenge): measure
        // the text precisely to hug it closely.
        const range = document.createRange();
        range.selectNodeContents(ancre);
        rect = range.getBoundingClientRect();
      } else {
        // "Wide" anchor (a whole row, like in classic mode): keep the
        // original behavior, based on the whole row.
        rect = ancre.getBoundingClientRect();
      }
      bouton.style.top = rect.top + rect.height / 2 + "px";
      bouton.style.left = rect.right + 4 + "px";
    }
    positionner();
    window.addEventListener("resize", positionner);
    window.addEventListener("scroll", positionner, true);

    bouton.addEventListener("click", () => {
      window.open(buildCartometaBatchUrl(rounds), "_blank");
    });
  }

  // Variant of the same button for modes with no "Total" row to anchor
  // to (Duels, Team Duels): anchored just above the first item of the
  // rounds list.
  function ajouterBoutonAuDessusListe(premierElement, rounds, id, suivreDefilement) {
    if (!rounds || rounds.length === 0) return;
    if (document.getElementById(id)) return; // already shown

    const bouton = document.createElement("div");
    bouton.id = id;
    bouton.style.display = "flex";
    bouton.style.alignItems = "center";
    bouton.style.gap = "6px";
    bouton.innerHTML =
      '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="3" width="16" height="18" rx="2"/><line x1="8" y1="8" x2="16" y2="8"/><line x1="8" y1="12" x2="16" y2="12"/><line x1="8" y1="16" x2="13" y2="16"/></svg><span>View all rounds</span>';
    bouton.title = "View all rounds on Cartometa";
    bouton.style.position = "fixed";
    bouton.style.padding = "4px 10px";
    bouton.style.background = obtenirParametres().couleurAccent;
    bouton.style.color = "#111";
    bouton.style.fontWeight = "bold";
    bouton.style.borderRadius = "14px";
    bouton.style.cursor = "pointer";
    bouton.style.zIndex = "999999";
    bouton.style.boxShadow = "0 2px 8px rgba(0,0,0,0.4)";
    bouton.style.fontSize = "13px";
    bouton.style.whiteSpace = "nowrap";
    document.body.appendChild(bouton);

    function positionner() {
      if (suivreDefilement) {
        // Team Duels: anchored to the column headers row ("Closest
        // Guess", "Health"...) rather than the first round item — that
        // header is itself "sticky" (it stops scrolling once it reaches
        // the top, same as the mini-map above it), so tracking it gives
        // our button the same correct stop-scrolling behavior for free.
        const entete = document.querySelector('[class*="playedRoundsHeader__"]') || premierElement;
        const rect = entete.getBoundingClientRect();
        bouton.style.top = Math.max(4, rect.top) + "px";
        bouton.style.left = rect.left + "px";
      } else {
        // Regular Duels: this screen doesn't scroll at all, so the
        // button is simply fixed just above the first round item —
        // its original, unchanged position.
        const rect = premierElement.getBoundingClientRect();
        bouton.style.top = Math.max(4, rect.top - 34) + "px";
        bouton.style.left = rect.left + "px";
      }
    }
    positionner();
    window.addEventListener("resize", positionner);
    // Only tracked on scroll where the list actually scrolls under a
    // sticky header (Team Duels). The regular Duels summary screen
    // doesn't scroll at all, so there's nothing to track there — doing
    // so anyway made the button drift for no reason.
    if (suivreDefilement) {
      window.addEventListener("scroll", positionner, true);
    }

    bouton.addEventListener("click", () => {
      window.open(buildCartometaBatchUrl(rounds), "_blank");
    });
  }

  // GeoGuessr is an SPA: navigating does NOT reload the document, so
  // this script never restarts itself when navigating elsewhere —
  // without this cleanup, injected icons and buttons would stay
  // displayed forever, even on unrelated pages. We periodically check
  // whether a reference element (e.g. the first item of the rounds
  // list) is still "connected" to the document; once it isn't (the page
  // changed), everything gets cleaned up.
  // Wraps a MutationObserver callback so that a whole burst of DOM
  // mutations (common during animations) only triggers the (costly)
  // wrapped function ONCE per rendered frame, instead of once per
  // individual mutation — same end result, much less redundant work.
  function grouperParFrame(fn) {
    let planifie = false;
    return function (...args) {
      if (planifie) return;
      planifie = true;
      requestAnimationFrame(() => {
        planifie = false;
        fn(...args);
      });
    };
  }

  // Our icons are always position:fixed (added directly to <body>, not
  // inside the list itself — needed elsewhere to avoid a sidebar's own
  // overflow:hidden clipping an icon that's meant to stick out past the
  // row). The flip side: nothing then clips our icon automatically when
  // its anchor row is no longer actually visible — whether because it
  // scrolled out of an internally-scrolling list, or because some other
  // element (e.g. a "sticky" map that stays in place while a list
  // scrolls underneath it) now visually covers that spot instead.
  // Rather than trying to reason about every possible CSS cause
  // (overflow, position:sticky, z-index...), this just asks the browser
  // directly what's actually rendered at the row's own center point.
  function estVisibleDansConteneurs(el) {
    // Grace period: some result screens animate rows into place
    // (staggered entrance animations), during which a row's real
    // position/covering elements are still settling — checking too
    // early caused a brief flicker right on page load. Freshly injected
    // rows are simply assumed visible for their first moment on screen.
    const injecteA = Number(el.dataset.cartometaInjectedAt);
    if (injecteA && Date.now() - injecteA < 1500) return true;

    const rect = el.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return false;

    const x = rect.left + rect.width / 2;
    const y = rect.top + rect.height / 2;
    if (x < 0 || y < 0 || x > window.innerWidth || y > window.innerHeight) return false;

    // First: is the row scrolled outside the visible bounds of one of
    // its own clipping/scrolling ancestors? (e.g. simply past the
    // bottom edge of a card, with nothing else drawn over it there —
    // elementsFromPoint below wouldn't catch this case on its own,
    // since there's no other element "covering" that empty spot.)
    let parent = el.parentElement;
    while (parent) {
      const styleParent = getComputedStyle(parent);
      const coupe =
        styleParent.overflow === "hidden" ||
        styleParent.overflowY === "hidden" ||
        styleParent.overflowY === "auto" ||
        styleParent.overflowY === "scroll" ||
        styleParent.overflow === "clip" ||
        styleParent.overflowY === "clip";
      if (coupe) {
        const rectParent = parent.getBoundingClientRect();
        if (y <= rectParent.top || y >= rectParent.bottom || x <= rectParent.left || x >= rectParent.right) {
          return false;
        }
      }
      parent = parent.parentElement;
    }

    // Second: is something else drawn on top of this exact point?
    // Using elementsFromPoint (the WHOLE stack at that point, top to
    // bottom) rather than elementFromPoint (topmost only) and skipping
    // our own injected overlays: our own icons/links are themselves
    // position:fixed with a very high z-index, and can sit exactly at
    // this same point — meaning a naive "what's on top here" check can
    // end up detecting OUR OWN icon instead of whatever is genuinely
    // covering the row underneath it (e.g. a "sticky" map that doesn't
    // scroll away). Every element we inject shares this same fixed +
    // huge-z-index signature, which reliably tells them apart from
    // GeoGuessr's own UI without needing a per-mode special case.
    const pile =
      typeof document.elementsFromPoint === "function" ? document.elementsFromPoint(x, y) : [];

    for (const candidat of pile) {
      const style = getComputedStyle(candidat);
      const estNotreProprePlaceholder = style.position === "fixed" && parseInt(style.zIndex, 10) >= 999999;
      if (estNotreProprePlaceholder) continue;
      return el === candidat || el.contains(candidat) || candidat.contains(el);
    }
    return false;
  }

  function surveillerNavigation(getElementReference, nettoyer) {
    const intervalId = setInterval(() => {
      const ref = getElementReference();
      if (ref && !ref.isConnected) {
        nettoyer();
        clearInterval(intervalId);
      }
    }, 1000);
  }
  // "Generation" counter: incremented every time routing is re-run (a
  // new game started without a full reload). Each mode captures the
  // generation in effect when it starts; if a newer generation starts
  // in the meantime (new game), the older instance disables itself in
  // its observer instead of running forever in the background and
  // interfering with the new game.
  let generationActuelle = 0;

  // ---------------------------------------------------------------
  // Captures game coordinates via network interception (fetch + XHR),
  // installed ONCE for the whole browsing session, independent of SPA
  // page changes. This interception used to be set up on every new
  // "generation" (new game started without a reload), which stacked
  // wrapping layers on window.fetch/XMLHttpRequest with every quickly
  // chained game — a source of hard-to-diagnose bugs where capture
  // would stop working without a full page reload. State now resets
  // itself based on the game's TOKEN (present in every response),
  // instead of relying on fragile URL-change timing.
  // ---------------------------------------------------------------
  let etatJeuActuel = { token: null, roundLocations: [], roundActuel: null };

  function extractRoundLocationsGlobal(data) {
    // Depending on the game mode, real coordinates live at
    // data.rounds[].lat / lng (classic games), or wrapped in a
    // "participants" array (Challenge): data.participants[0].round /
    // .rounds instead of data.round / .rounds directly.
    const donneesJeu = Array.isArray(data?.participants) ? data.participants[0] : data;
    const token = donneesJeu?.token || null;

    // New game detected (token different from the one we were tracking):
    // fully reset the state, regardless of how we got to this new game
    // (full reload or internal SPA navigation).
    if (token && token !== etatJeuActuel.token) {
      console.log("[GeoGuessr→Cartometa] New game detected, token:", token);
      etatJeuActuel = { token, roundLocations: [], roundActuel: null };
    }

    // IMPORTANT: network requests can resolve out of order (an older
    // request can take longer to respond than a more recent one).
    // Without a guard, a late/stale response would overwrite up-to-date
    // data with outdated data. So a new value is only accepted if it's
    // for a round STRICTLY ahead of what we already have.
    if (
      typeof donneesJeu?.round === "number" &&
      donneesJeu.round <= (etatJeuActuel.roundActuel ?? 0)
    ) {
      console.log(
        "[GeoGuessr→Cartometa] Response ignored (round",
        donneesJeu.round,
        "<= already known round",
        etatJeuActuel.roundActuel,
        ") — likely arrived late (out of order)."
      );
      return;
    }

    if (Array.isArray(donneesJeu?.rounds)) {
      etatJeuActuel.roundLocations = donneesJeu.rounds
        .filter((round) => typeof round.lat === "number" && typeof round.lng === "number")
        .map((round) => ({ lat: round.lat, lng: round.lng }));
      console.log("[GeoGuessr→Cartometa] Locations captured:", etatJeuActuel.roundLocations);
    }

    // donneesJeu.round is the current (or just-played) round number
    // according to the API itself — more reliable than inferring it from
    // the length of rounds, which may already contain coordinates for
    // rounds not played yet.
    if (typeof donneesJeu?.round === "number") {
      etatJeuActuel.roundActuel = donneesJeu.round;
      console.log("[GeoGuessr→Cartometa] Current round reported by the API:", etatJeuActuel.roundActuel);
    }
  }

  // ---------------------------------------------------------------
  // Live Challenge (Party mode) is served from a completely different
  // domain (game-server.geoguessr.com, not www.geoguessr.com) and uses
  // its own JSON shape entirely — coordinates live nested at
  // rounds[].question.panoramaQuestionPayload.panorama.lat / .lng,
  // rather than a flat round.lat / .lng. Kept as separate state (keyed
  // by roundNumber rather than a plain array, since rounds may arrive
  // gradually and out of order as the match progresses) instead of
  // reusing etatJeuActuel, since the two formats have nothing in common
  // beyond both being "round coordinates".
  // ---------------------------------------------------------------
  let etatLiveChallenge = { gameId: null, roundLocations: {} };

  function extractRoundLocationsLiveChallenge(data) {
    if (!data || !Array.isArray(data.rounds)) return;

    if (data.gameId && data.gameId !== etatLiveChallenge.gameId) {
      console.log("[GeoGuessr→Cartometa] New Live Challenge game detected:", data.gameId);
      etatLiveChallenge = { gameId: data.gameId, roundLocations: {} };
    }

    data.rounds.forEach((round) => {
      const panorama = round?.question?.panoramaQuestionPayload?.panorama;
      if (
        typeof round?.roundNumber === "number" &&
        panorama &&
        typeof panorama.lat === "number" &&
        typeof panorama.lng === "number"
      ) {
        etatLiveChallenge.roundLocations[round.roundNumber] = { lat: panorama.lat, lng: panorama.lng };
      }
    });

    console.log("[GeoGuessr→Cartometa] Live Challenge locations captured:", etatLiveChallenge.roundLocations);
  }

  // ---------------------------------------------------------------
  // Party Duels (the newer "game-summary-2" results screen) doesn't go
  // through fetch/XHR at all — the whole match plays out over a
  // WebSocket connection instead, carrying a mix of binary frames (most
  // of them) and JSON text frames tagged with a "code" field. The one
  // we care about, "DuelFinished", carries the full match state
  // (duel.state.rounds[], each with a nested .panorama.lat / .lng) —
  // arriving right as the results screen appears.
  // ---------------------------------------------------------------
  let etatPartyDuels = { gameId: null, roundLocations: {} };

  function extractRoundLocationsPartyDuels(message) {
    const state = message?.duel?.state;
    if (!state || !Array.isArray(state.rounds)) return;

    if (state.gameId && state.gameId !== etatPartyDuels.gameId) {
      console.log("[GeoGuessr→Cartometa] New Party Duels game detected:", state.gameId);
      etatPartyDuels = { gameId: state.gameId, roundLocations: {} };
    }

    state.rounds.forEach((round) => {
      const panorama = round?.panorama;
      if (
        typeof round?.roundNumber === "number" &&
        panorama &&
        typeof panorama.lat === "number" &&
        typeof panorama.lng === "number"
      ) {
        etatPartyDuels.roundLocations[round.roundNumber] = { lat: panorama.lat, lng: panorama.lng };
      }
    });

    console.log("[GeoGuessr→Cartometa] Party Duels locations captured:", etatPartyDuels.roundLocations);
  }

  function installerInterceptionWebSocket() {
    if (typeof window.WebSocket === "undefined") return;

    const OriginalWebSocket = window.WebSocket;

    function WebSocketIntercepte(...args) {
      const socket = new OriginalWebSocket(...args);
      socket.addEventListener("message", (event) => {
        try {
          if (typeof event.data !== "string") return; // skip binary frames, most of them are
          const message = JSON.parse(event.data);
          extractRoundLocationsPartyDuels(message);
        } catch (e) {
          // not JSON, or unrelated to what we're looking for — ignore silently
        }
      });
      return socket;
    }
    WebSocketIntercepte.prototype = OriginalWebSocket.prototype;
    Object.setPrototypeOf(WebSocketIntercepte, OriginalWebSocket);
    window.WebSocket = WebSocketIntercepte;
  }

  // ---------------------------------------------------------------
  // Intercepts google.maps.Map instance creation, to later draw a
  // meta's polygon directly on GeoGuessr's own map.
  //
  // IMPORTANT (found through testing): watching only the very first
  // assignment of window.google (or google.maps) isn't enough — Google's
  // loader appears to build this object up in several steps (e.g.
  // creating an near-empty `google.maps` namespace first, then adding
  // `.Map` onto that SAME object a moment later as a separate property
  // write, which a one-shot "assignment" trap never sees). The fix is a
  // generic property watcher, applied in a cascade: watch `window.google`
  // for its value, then watch `.maps` on WHATEVER that turns out to be,
  // then watch `.Map` on WHATEVER that turns out to be — catching the
  // constructor no matter which of these ends up being assigned first,
  // last, all at once, or piecemeal over time.
  // ---------------------------------------------------------------
  let instancesCarteGoogle = [];

  // Watches a single property on an object: fires the callback
  // immediately if it's already set, AND again every time it gets
  // (re)assigned afterwards.
  function surveillerPropriete(objet, propriete, callback) {
    if (!objet) return;
    if (objet[propriete] !== undefined) {
      callback(objet[propriete]);
    }
    let valeurReelle = objet[propriete];
    try {
      Object.defineProperty(objet, propriete, {
        configurable: true,
        get() {
          return valeurReelle;
        },
        set(v) {
          // Avoids infinite recursion: when our own callback below
          // reassigns this same property (e.g. installing the wrapped
          // Map constructor), that reassignment would otherwise
          // re-trigger this very setter with the exact same value.
          if (v === valeurReelle) return;
          valeurReelle = v;
          callback(v);
        },
      });
    } catch (e) {
      // best effort — if this particular property can't be trapped
      // (already non-configurable, etc.), later (re-)assignments to it
      // just won't be caught, but earlier/current values still are
    }
  }

  function envelopperConstructeurMap(ConstructeurOriginal) {
    if (!ConstructeurOriginal || ConstructeurOriginal.__cartometaWrapped) return ConstructeurOriginal;

    function MapIntercepte(...args) {
      const instance = new ConstructeurOriginal(...args);
      instancesCarteGoogle.push(instance);
      console.log(
        "[GeoGuessr→Cartometa] Google Maps instance captured (total:",
        instancesCarteGoogle.length,
        ")",
        instance
      );
      return instance;
    }
    MapIntercepte.prototype = ConstructeurOriginal.prototype;
    Object.setPrototypeOf(MapIntercepte, ConstructeurOriginal);
    MapIntercepte.__cartometaWrapped = true;
    console.log("[GeoGuessr→Cartometa] google.maps.Map constructor intercepted.");
    return MapIntercepte;
  }

  (function installerInterceptionGoogleMaps() {
    if (location.hostname !== "www.geoguessr.com") return; // useless elsewhere (e.g. cartometa.com, which defaults to OpenStreetMap)

    surveillerPropriete(window, "google", (googleObjet) => {
      surveillerPropriete(googleObjet, "maps", (mapsObjet) => {
        surveillerPropriete(mapsObjet, "Map", (ConstructeurMap) => {
          mapsObjet.Map = envelopperConstructeurMap(ConstructeurMap);
        });
      });
    });
  })();

  // Among every captured instance, find the one currently VISIBLE on
  // screen — not just "connected" to the document, but actually
  // rendered with a non-zero size and not hidden via CSS. This matters
  // for modes like Duels, where several map instances can exist at
  // once (one per round) even though only one is actually shown at any
  // given time; simply picking "the most recently created connected
  // one" isn't reliable there. Among the visible candidates (there
  // should normally be at most one), we still prefer the most recently
  // created as a tie-breaker.
  function obtenirCarteGoogleActuelle() {
    let meilleureInstance = null;

    for (let i = instancesCarteGoogle.length - 1; i >= 0; i--) {
      const instance = instancesCarteGoogle[i];
      try {
        const div = instance.getDiv();
        if (!div || !div.isConnected) continue;

        const rect = div.getBoundingClientRect();
        const estVisible =
          rect.width > 0 &&
          rect.height > 0 &&
          getComputedStyle(div).visibility !== "hidden" &&
          getComputedStyle(div).display !== "none";

        if (estVisible) return instance; // most recent visible match wins outright

        if (!meilleureInstance) meilleureInstance = instance; // fallback: most recent connected one, even if not currently visible
      } catch (e) {
        // skip this instance if it can't answer getDiv() for some reason
      }
    }

    return meilleureInstance;
  }

  let polygoneActuelSurCarte = null;

  // Draws a meta's footprint directly on GeoGuessr's own round map (not
  // in our popup): a real google.maps.Polygon attached to their map
  // instance follows pan/zoom natively, no extra work needed on our
  // side for that part.
  function afficherPolygoneSurCarte(geometrie) {
    supprimerPolygoneDeLaCarte();
    if (!geometrie || !geometrie.type) return;

    const carte = obtenirCarteGoogleActuelle();
    if (!carte) {
      console.log("[GeoGuessr→Cartometa] No Google Maps instance found to draw the polygon on.");
      return;
    }

    function convertirAnneau(anneau) {
      return anneau.map(([lng, lat]) => ({ lat, lng }));
    }

    let paths;
    if (geometrie.type === "Polygon") {
      paths = geometrie.coordinates.map(convertirAnneau);
    } else if (geometrie.type === "MultiPolygon") {
      paths = geometrie.coordinates.flatMap((polygone) => polygone.map(convertirAnneau));
    } else {
      return; // unsupported type (Point, LineString...) — rare for a footprint
    }

    const couleur = obtenirParametres().couleurAccent;

    try {
      polygoneActuelSurCarte = new google.maps.Polygon({
        paths,
        strokeColor: couleur,
        strokeOpacity: 0.9,
        strokeWeight: 2,
        fillColor: couleur,
        fillOpacity: obtenirParametres().opaciteSilhouette / 100,
        map: carte,
      });
    } catch (e) {
      console.log("[GeoGuessr→Cartometa] Error while drawing the polygon:", e);
    }
  }

  function supprimerPolygoneDeLaCarte() {
    if (polygoneActuelSurCarte) {
      try {
        polygoneActuelSurCarte.setMap(null);
      } catch (e) {
        // fine, nothing more we can do if this fails
      }
      polygoneActuelSurCarte = null;
    }
  }

  let interceptionReseauInstallee = false;
  function installerInterceptionReseau() {
    if (interceptionReseauInstallee) return; // never more than once per session
    interceptionReseauInstallee = true;

    const originalFetch = window.fetch;
    window.fetch = async function (...args) {
      const response = await originalFetch.apply(this, args);

      try {
        // args[0] can be a plain string, a Request object (has a .url
        // property), or a native URL instance (has .href, not .url) —
        // handle all three cases.
        let url = null;
        if (typeof args[0] === "string") {
          url = args[0];
        } else if (args[0] instanceof URL) {
          url = args[0].href;
        } else if (args[0] && typeof args[0].url === "string") {
          url = args[0].url;
        }

        // GeoGuessr game endpoints contain "/api/v3/games/" or
        // "/api/v4/games/" depending on the mode. Live Challenge (Party
        // mode) uses a completely different pattern instead.
        if (url && /\/api\/v[0-9]+\/games\//.test(url)) {
          console.log("[GeoGuessr→Cartometa] games/ request intercepted:", url);
          const clone = response.clone();
          clone.json().then((data) => {
            extractRoundLocationsGlobal(data);
          }).catch((e) => {
            console.log("[GeoGuessr→Cartometa] Error parsing JSON response:", e);
          });
        } else if (url && /\/api\/live-challenge\//.test(url)) {
          console.log("[GeoGuessr→Cartometa] live-challenge/ request intercepted:", url);
          const clone = response.clone();
          clone.json().then((data) => {
            extractRoundLocationsLiveChallenge(data);
          }).catch((e) => {
            console.log("[GeoGuessr→Cartometa] Error parsing Live Challenge JSON response:", e);
          });
        }
      } catch (e) {
        // never block the original fetch on error
      }

      return response;
    };

    // Extra safety: if a particular request goes through XMLHttpRequest
    // instead of fetch, the interception above would never see it. So we
    // intercept XMLHttpRequest too.
    const originalXHROpen = XMLHttpRequest.prototype.open;
    const originalXHRSend = XMLHttpRequest.prototype.send;

    XMLHttpRequest.prototype.open = function (method, url, ...reste) {
      this._cartometaURL = url;
      return originalXHROpen.call(this, method, url, ...reste);
    };

    XMLHttpRequest.prototype.send = function (...args) {
      this.addEventListener("load", function () {
        try {
          const url = this._cartometaURL;
          if (url && /\/api\/v[0-9]+\/games\//.test(url)) {
            console.log("[GeoGuessr→Cartometa] XHR games/ request intercepted:", url);
            const data = JSON.parse(this.responseText);
            extractRoundLocationsGlobal(data);
          } else if (url && /\/api\/live-challenge\//.test(url)) {
            console.log("[GeoGuessr→Cartometa] XHR live-challenge/ request intercepted:", url);
            const data = JSON.parse(this.responseText);
            extractRoundLocationsLiveChallenge(data);
          }
        } catch (e) {
          // silently ignore (non-JSON response, etc.)
        }
      });
      return originalXHRSend.apply(this, args);
    };
  }

  // The domain this script runs on decides which side to run (Tampermonkey
  // injects it on both, via the two @match lines above).
  if (location.hostname === 'www.geoguessr.com') {
    installerInterceptionReseau();
    installerInterceptionWebSocket();
    runOnGeoGuessr();

    // GeoGuessr is an SPA: if the user starts a game (or navigates to
    // another relevant page) WITHOUT a full reload — which is the case
    // most of the time, e.g. clicking "Play" from the homepage — this
    // script, which only runs ONCE on initial page load, never "wakes
    // up" for that new page: the routing above was decided once, based
    // on the starting URL. So we continuously watch for URL changes and
    // re-run routing every time it changes.
    // Only the URL's PATH is compared (not query params or hash), which
    // can change mid-game without it being a real new page — comparing
    // the full URL would have invalidated the current game (and thus
    // closed/blocked the auto preview) on every unrelated minor change.
    let dernierChemin = location.pathname;

    function reverifierApresNavigation() {
      if (location.pathname !== dernierChemin) {
        dernierChemin = location.pathname;
        runOnGeoGuessr();
      }
    }

    // Periodic check, kept only as a safety net now (catches anything
    // the event-based approach below might miss for any reason) —
    // slowed down to every 3s instead of every 500ms, since it's no
    // longer the primary detection method.
    setInterval(reverifierApresNavigation, 3000);

    // Event-based check: Next.js (used by GeoGuessr) navigates
    // internally via the History API (pushState/replaceState), rather
    // than a full page load. Hooking these lets us react at the exact
    // moment navigation happens, instead of waiting for the next
    // periodic check (up to 500ms later) — this is what was causing our
    // icons/detection logic to sometimes not "wake up" for a new page.
    try {
      const originalPushState = history.pushState;
      history.pushState = function (...args) {
        const resultat = originalPushState.apply(this, args);
        reverifierApresNavigation();
        return resultat;
      };

      const originalReplaceState = history.replaceState;
      history.replaceState = function (...args) {
        const resultat = originalReplaceState.apply(this, args);
        reverifierApresNavigation();
        return resultat;
      };

      window.addEventListener("popstate", reverifierApresNavigation);
    } catch (e) {
      // fine if this fails for some reason — the periodic check above
      // still covers us, just with the earlier up-to-500ms delay
    }
  } else if (location.hostname === 'cartometa.com') {
    runOnCartometa();
  }

  // =========================================================
  // PART 1 — GeoGuessr: inject links to Cartometa
  // =========================================================
  function runOnGeoGuessr() {
    generationActuelle += 1;
    const maGeneration = generationActuelle;

    // Settings icon: shown on every page, regardless of the game mode
    // detected below.
    ajouterIconeParametres();
    ajouterBoutonBasculeAutoShow();

    // GeoGuessr has several recap screen types depending on the game
    // mode (classic, Duels, Challenge...), with very different
    // structures. We detect the page type from its URL and apply the
    // right handling.
    if (/\/duels\/[^/]+\/summary/.test(location.pathname)) {
      runOnDuelsSummary(buildCartometaUrl, maGeneration);
    } else if (/^\/duels\/[^/]+$/.test(location.pathname)) {
      runOnPartyDuels(buildCartometaUrl, maGeneration);
    } else if (/^\/team-duels\/[^/]+\/summary/.test(location.pathname)) {
      runOnTeamDuelsSummary(buildCartometaUrl, maGeneration);
    } else if (/^\/team-duels\/[^/]+$/.test(location.pathname)) {
      // Party Team Duels' results screen reuses the exact same
      // "game-summary-2" layout and WebSocket message shape as regular
      // Party Duels — same function handles both.
      runOnPartyDuels(buildCartometaUrl, maGeneration);
    } else if (/^\/results\//.test(location.pathname)) {
      runOnChallengeResults(buildCartometaUrl, maGeneration);
    } else if (/^\/live-challenge\//.test(location.pathname)) {
      runOnLiveChallenge(buildCartometaUrl, maGeneration);
    } else {
      runOnClassicResults(buildCartometaUrl, maGeneration);
    }
  }

  // ---- 1.2a Classic recap screen (Singleplayer games) ----
  function runOnClassicResults(buildCartometaUrl, maGeneration) {
    // Game coordinates are now captured by a GLOBAL network interceptor,
    // installed once for the whole session (see installerInterceptionReseau
    // above) — we just read etatJeuActuel here, no duplicate interception.

    // Intermediate score screen (between each round, before the next one
    // or the final recap): unlike the final recap, only ONE round is
    // shown at a time. We read etatJeuActuel (global state, shared and
    // updated by the network interceptor installed once for the whole
    // session — see installerInterceptionReseau above), which fills up
    // as the game progresses.
    let dernierRoundAffiche = 0;
    let fenetreApercuAutoActuelle = null; // to close it on the next round
    let timeoutFermetureApercu = null;

    function detecterEtAfficherApercuRoundEnCours() {
      // Safety net: if a newer game started in the meantime, this
      // closure must do nothing at all anymore (neither open nor close a
      // window), to avoid acting on the wrong game.
      if (maGeneration !== generationActuelle) return;

      // Classic mode uses "round-result_wrapper__"; Streak mode uses a
      // completely different structure ("streak-round-result_root__")
      // for what is visually a very similar screen — both are checked
      // here so this same detection (and the auto-preview logic below)
      // covers both modes.
      const surEcranDeScore = !!document.querySelector(
        '[class*="round-result_wrapper__"], [class*="streak-round-result_root__"]'
      );

      // As soon as we leave the score screen (next round, or moving to
      // the final recap), close the preview that was open for the
      // previous round: otherwise it stays displayed and gets in the way
      // of playing the next round. We wait a short delay before actually
      // closing (instead of closing instantly): this screen's entrance
      // animations (or even a blocked popup attempt, which can also
      // briefly disrupt rendering) can make the element disappear then
      // reappear, which would close the window before we even had a
      // chance to see the message if we reacted too fast.
      if (!surEcranDeScore) {
        if (!timeoutFermetureApercu) {
          timeoutFermetureApercu = setTimeout(() => {
            if (fenetreApercuAutoActuelle) {
              fenetreApercuAutoActuelle.fermerAvecMemoire();
              fenetreApercuAutoActuelle = null;
            }
            // We've really left the score screen (next round, back to
            // home...): the reopen icon must no longer be available once
            // in-game, otherwise it would let players check a meta
            // during the game itself (which amounts to cheating).
            masquerIconeReouverture();
            dernierApercuFerme = null;
            timeoutFermetureApercu = null;
          }, 650);
        }
        return;
      }

      // We're on the score screen: cancel any pending scheduled close
      // (false alarm / flicker).
      if (timeoutFermetureApercu) {
        clearTimeout(timeoutFermetureApercu);
        timeoutFermetureApercu = null;
      }

      if (!obtenirParametres().apercuAutoParRound) {
        console.log("[GeoGuessr→Cartometa] Auto preview disabled in settings, skipping.");
        return;
      }

      if (etatJeuActuel.roundActuel === null) {
        console.log(
          "[GeoGuessr→Cartometa] Score screen detected but the round number isn't known yet (the network request may not have responded yet, or wasn't intercepted)."
        );
        return;
      }
      if (etatJeuActuel.roundActuel <= dernierRoundAffiche) return; // already shown for this round

      const loc = etatJeuActuel.roundLocations[etatJeuActuel.roundActuel - 1];
      if (!loc) {
        console.log(
          "[GeoGuessr→Cartometa] Round",
          etatJeuActuel.roundActuel,
          "reported but coordinates are missing."
        );
        return;
      }

      dernierRoundAffiche = etatJeuActuel.roundActuel;
      console.log(
        "[GeoGuessr→Cartometa] Opening auto preview for round",
        etatJeuActuel.roundActuel,
        "lat/lng:",
        loc.lat,
        loc.lng
      );
      fenetreApercuAutoActuelle = ouvrirApercuMetas(loc.lat, loc.lng, true);
    }

    // ---- 1.3 Inject links on the final recap screen ----
    const injectedLinks = []; // { link, row } — for repositioning as needed
    const iconesApercu = []; // 🖼️ icons, manage their own positioning
    let premiereLigne = null; // to detect when this page is left

    function positionLink(link, row) {
      const rect = row.getBoundingClientRect();
      link.style.top = rect.top + rect.height / 2 + "px";
      link.style.left = rect.right + 8 + "px";
    }

    function repositionAllLinks() {
      injectedLinks.forEach(({ link, row }) => {
        positionLink(link, row);
        const visible = estVisibleDansConteneurs(row);
        link.style.display = visible ? "" : "none";
        if (link._iconeMeta) link._iconeMeta.style.display = visible ? "" : "none";
      });
    }

    // The score sidebar likely has a fixed width with "overflow:
    // hidden" somewhere in its ancestors: anything added INSIDE that
    // flow that exceeds the sidebar's width is invisible and
    // unclickable, even if visually "outside" the score box. To avoid
    // this, the icon is NOT inserted into the list: it's added directly
    // to <body>, in "fixed" position, with coordinates computed from the
    // score row's real position on screen.
    function injectLinks() {
      if (etatJeuActuel.roundLocations.length === 0) return;

      const allRows = document.querySelectorAll('[class*="result-list_listItemWrapper__"]');
      if (allRows.length > 0 && !premiereLigne) premiereLigne = allRows[0];

      const roundRows = Array.from(allRows).filter((row) => {
        if (row.dataset.cartometaInjected) return false;
        const roundNumberEl = row.querySelector('[class*="result-list_roundNumber__"]');
        const label = roundNumberEl ? roundNumberEl.textContent.trim() : "";
        return label !== "" && label.toLowerCase() !== "total";
      });

      roundRows.forEach((row, index) => {
        const loc = etatJeuActuel.roundLocations[index];
        if (!loc) return;

        const link = document.createElement("a");
        link.href = buildCartometaUrl(loc.lat, loc.lng);
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.innerHTML = '<svg width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>';
        link.style.color = "#fff";
        link.style.filter = "drop-shadow(0 1px 3px rgba(0,0,0,0.9))";
        link.title = "Open on Cartometa";
        link.style.position = "fixed";
        link.style.display = "inline-flex";
        link.style.transform = "translateY(-50%)"; // vertical centering on the row
        link.style.textDecoration = "none";
        link.style.cursor = "pointer";
        link.style.zIndex = "999999";
        link.style.pointerEvents = "auto";

        document.body.appendChild(link);
        positionLink(link, row);
        injectedLinks.push({ link, row });

        // Separate array: this icon handles its own positioning
        // (anchored to the 🔎 link itself), so we don't want it going
        // through positionLink/repositionAllLinks, which would overwrite
        // it with the same formula as the 🔎 link (stacking them). We
        // still keep a reference on the link itself so its visibility
        // can be kept in sync with the row (see estVisibleDansConteneurs).
        const iconeApercuClassique = ajouterIconeApercu(link, loc.lat, loc.lng, 21);
        link._iconeMeta = iconeApercuClassique;
        iconesApercu.push(iconeApercuClassique);

        row.dataset.cartometaInjected = "true";
        row.dataset.cartometaInjectedAt = String(Date.now());
      });

      // Final "all rounds" button, anchored to the "Total" row (looked
      // up separately, without touching the logic above).
      const totalRow = Array.from(allRows).find((row) => {
        const roundNumberEl = row.querySelector('[class*="result-list_roundNumber__"]');
        const label = roundNumberEl ? roundNumberEl.textContent.trim().toLowerCase() : "";
        return label === "total";
      });
      if (totalRow && etatJeuActuel.roundLocations.length > 0) {
        const tousLesRounds = etatJeuActuel.roundLocations.map((loc, i) => ({
          roundNumber: i + 1,
          lat: loc.lat,
          lng: loc.lng,
        }));
        ajouterBoutonTousLesRounds(totalRow, tousLesRounds, "cartometa-bouton-total-classique", 23);
      }

      // Streak mode's final recap (when the streak ends) uses a
      // completely different list structure from classic's own final
      // recap — one row per round, each showing a country name rather
      // than a "Round N" label, with no "Total" row. Handled separately
      // here, reusing the same accumulated round data (etatJeuActuel),
      // anchoring icons to the right of the country name as requested.
      const streakRows = document.querySelectorAll('[data-qa="streak-result-list-item"]');
      if (streakRows.length > 0 && etatJeuActuel.roundLocations.length > 0) {
        if (!premiereLigne) premiereLigne = streakRows[0];

        streakRows.forEach((row, index) => {
          if (row.dataset.cartometaInjected) return;
          const loc = etatJeuActuel.roundLocations[index];
          if (!loc) return;

          const nomEl = row.querySelector('[class*="streak-result-list_name__"]');
          if (!nomEl) return;

          const link = document.createElement("a");
          link.href = buildCartometaUrl(loc.lat, loc.lng);
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          link.innerHTML =
            '<svg width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>';
          link.style.color = "#fff";
          link.style.filter = "drop-shadow(0 1px 3px rgba(0,0,0,0.9))";
          link.title = "Open on Cartometa";
          link.style.position = "fixed";
          link.style.display = "inline-flex";
          link.style.transform = "translateY(-50%)"; // vertical centering on the country name
          link.style.textDecoration = "none";
          link.style.cursor = "pointer";
          link.style.zIndex = "999999";
          link.style.pointerEvents = "auto";

          document.body.appendChild(link);
          positionLink(link, nomEl);
          injectedLinks.push({ link, row: nomEl });

          // Separate array: this icon handles its own positioning
          // (anchored to the 🔎 link itself), same reasoning as the
          // classic-mode rounds above. Kept referenced on the link too,
          // for visibility syncing (see estVisibleDansConteneurs).
          const iconeApercuStreak = ajouterIconeApercu(link, loc.lat, loc.lng, 21);
          link._iconeMeta = iconeApercuStreak;
          iconesApercu.push(iconeApercuStreak);

          row.dataset.cartometaInjected = "true";
          row.dataset.cartometaInjectedAt = String(Date.now());
        });
      }
    }

    window.addEventListener("resize", repositionAllLinks);
    window.addEventListener("scroll", repositionAllLinks, true);

    const observer = new MutationObserver(
      grouperParFrame(() => {
        if (maGeneration !== generationActuelle) {
          observer.disconnect();
          return;
        }
        injectLinks();
        repositionAllLinks();
        detecterEtAfficherApercuRoundEnCours();
      })
    );

    observer.observe(document.body, { childList: true, subtree: true });

    surveillerNavigation(
      () => premiereLigne,
      () => {
        injectedLinks.forEach(({ link }) => link.remove());
        iconesApercu.forEach((icone) => icone.remove());
        const boutonTotal = document.getElementById("cartometa-bouton-total-classique");
        if (boutonTotal) boutonTotal.remove();
        observer.disconnect();
        window.removeEventListener("resize", repositionAllLinks);
        window.removeEventListener("scroll", repositionAllLinks, true);
      }
    );
  }

  // ---- 1.2b Duels recap screen ----
  function runOnDuelsSummary(buildCartometaUrl, maGeneration) {
    // Unlike classic mode, GeoGuessr embeds all game data (including
    // each round's real coordinates) directly in a JSON blob on the page
    // (__NEXT_DATA__), used by the Next.js framework to "hydrate" the
    // page. This is simpler and more reliable than intercepting network
    // calls: no need to wait for a request, the data is already there on
    // load.
    function extraireManchesDuels() {
      try {
        const scriptEl = document.getElementById('__NEXT_DATA__');
        if (!scriptEl) return [];
        const data = JSON.parse(scriptEl.textContent);
        const rounds = data?.props?.pageProps?.game?.rounds;
        if (!Array.isArray(rounds)) return [];
        return rounds
          .filter((r) => typeof r.lat === "number" && typeof r.lng === "number")
          .map((r) => ({ roundNumber: r.roundNumber, lat: r.lat, lng: r.lng }));
      } catch (e) {
        return [];
      }
    }

    // IMPORTANT: this used to be read ONCE, right here, with the whole
    // function bailing out permanently if empty. That created a race
    // condition on SPA navigation (no full reload): if this ran before
    // GeoGuessr finished updating __NEXT_DATA__ for the new page, it
    // would fail forever, with icons never appearing until a manual
    // refresh — exactly the bug reported by testing. It's now re-read
    // on every DOM mutation instead (see injectLinks below), until data
    // is actually found.
    let roundLocations = extraireManchesDuels();

    const injectedLinks = []; // { link, li }
    const iconesApercu = []; // 🖼️ icons, manage their own positioning
    let premierElementListe = null; // for the "all rounds" button
    let numeroRoundApercuOuvert = null; // which round our preview window currently shows, if any

    function positionLink(link, li) {
      const rect = li.getBoundingClientRect();
      link.style.top = rect.top + rect.height / 2 + "px";
      link.style.left = rect.right + 8 + "px";
    }

    function repositionAllLinks() {
      injectedLinks.forEach(({ link, li }) => {
        positionLink(link, li);
        const visible = estVisibleDansConteneurs(li);
        link.style.display = visible ? "" : "none";
        if (link._iconeMeta) link._iconeMeta.style.display = visible ? "" : "none";
      });
    }

    // Chaque manche est un <li class="duel-breakdown_roundItem__...">
    // contenant un <span class="duel-breakdown_roundNumber__...">
    // with the text "Round N". We extract N to precisely match the
    // right link to the right round number, rather than relying on
    // display order.
    function injectLinks() {
      if (roundLocations.length === 0) {
        roundLocations = extraireManchesDuels(); // retry: __NEXT_DATA__ may not have been ready yet
        if (roundLocations.length === 0) return; // still nothing, wait for the next DOM mutation
      }

      const items = document.querySelectorAll('[class*="duel-breakdown_roundItem__"]');
      const roundsPourPanneau = [];

      items.forEach((li) => {
        if (!premierElementListe) premierElementListe = li;

        const numEl = li.querySelector('[class*="duel-breakdown_roundNumber__"]');
        const texte = numEl ? numEl.textContent.trim() : "";
        const match = texte.match(/(\d+)/);
        if (!match) return;

        const numero = parseInt(match[1], 10);
        const loc = roundLocations.find((r) => r.roundNumber === numero);
        if (!loc) return;

        // Grab the flag image if present, for the "all rounds" panel
        // (even if this round's icon has already been injected
        // elsewhere).
        const imgDrapeau = li.querySelector('img');
        roundsPourPanneau.push({
          roundNumber: numero,
          lat: loc.lat,
          lng: loc.lng,
          flagSrc: imgDrapeau ? imgDrapeau.src : null,
        });

        if (li.dataset.cartometaInjected) return;

        // Anchor the icon on the flag image itself. We target the <img>
        // tag directly rather than a generated CSS class (like
        // "duel-breakdown_roundCountry__xxxxx"): those classes change on
        // every GeoGuessr deploy, while the flag <img> tag stays stable.
        const ancre = imgDrapeau || li;

        const link = document.createElement("a");
        link.href = buildCartometaUrl(loc.lat, loc.lng);
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.innerHTML = '<svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>';
        link.style.color = "#fff";
        link.style.filter = "drop-shadow(0 1px 3px rgba(0,0,0,0.9))";
        link.title = "Open on Cartometa";
        link.style.position = "fixed";
        link.style.display = "inline-flex";
        link.style.transform = "translateY(-50%)";
        link.style.textDecoration = "none";
        link.style.cursor = "pointer";
        link.style.zIndex = "999999";
        link.style.pointerEvents = "auto";

        document.body.appendChild(link);
        positionLink(link, ancre);
        injectedLinks.push({ link, li: ancre });

        const iconeApercu = ajouterIconeApercu(link, loc.lat, loc.lng);
        link._iconeMeta = iconeApercu;
        iconesApercu.push(iconeApercu);

        // Duels-specific: unlike other modes, each round here has its
        // OWN separate map/panorama, only one of which is actually
        // displayed at a time (whichever round is currently selected in
        // GeoGuessr's own list). Two things follow from that:
        //
        // 1. Opening the metas preview for a round should also select
        //    that round in GeoGuessr's UI, so its map is the one
        //    actually visible (and so our polygon-drawing code finds
        //    the right one to draw on).
        // 2. If the user then selects a DIFFERENT round while our
        //    preview is open, the preview no longer matches what's
        //    on screen and should close automatically.
        iconeApercu.addEventListener("click", () => {
          numeroRoundApercuOuvert = numero;
          try {
            // The actual clickable element that switches the displayed
            // round is a specific child (duel-breakdown_roundTop__...),
            // not the <li> itself — clicking the <li> directly doesn't
            // trigger its handler, since synthetic clicks only bubble
            // UP through ancestors, not down into descendants.
            const zoneCliquable = li.querySelector('[class*="duel-breakdown_roundTop__"]') || li;
            zoneCliquable.dispatchEvent(
              new MouseEvent("click", { bubbles: true, cancelable: true, view: window })
            );
          } catch (e) {
            // fine if this fails, the preview still opens either way
          }
        });

        li.addEventListener("click", () => {
          if (numeroRoundApercuOuvert === null || numeroRoundApercuOuvert === numero) return;
          const fenetreOuverte = document.getElementById("cartometa-apercu-metas");
          if (fenetreOuverte) {
            if (typeof fenetreOuverte.fermerAvecMemoire === "function") {
              fenetreOuverte.fermerAvecMemoire();
            } else {
              fenetreOuverte.remove();
            }
          }
          numeroRoundApercuOuvert = null;
        });

        li.dataset.cartometaInjected = "true";
        li.dataset.cartometaInjectedAt = String(Date.now());
      });

      if (premierElementListe && roundsPourPanneau.length > 0) {
        ajouterBoutonAuDessusListe(premierElementListe, roundsPourPanneau, "cartometa-bouton-liste-duels", false);
      }
    }

    window.addEventListener("resize", repositionAllLinks);
    window.addEventListener("scroll", repositionAllLinks, true);

    const observer = new MutationObserver(
      grouperParFrame(() => {
        if (maGeneration !== generationActuelle) {
          observer.disconnect();
          return;
        }
        injectLinks();
        repositionAllLinks();
      })
    );

    observer.observe(document.body, { childList: true, subtree: true });

    surveillerNavigation(
      () => premierElementListe,
      () => {
        injectedLinks.forEach(({ link }) => link.remove());
        iconesApercu.forEach((icone) => icone.remove());
        const bouton = document.getElementById("cartometa-bouton-liste-duels");
        if (bouton) bouton.remove();
        observer.disconnect();
        window.removeEventListener("resize", repositionAllLinks);
        window.removeEventListener("scroll", repositionAllLinks, true);
      }
    );
  }
  function runOnTeamDuelsSummary(buildCartometaUrl, maGeneration) {
    // Same idea as classic Duels: coordinates live in __NEXT_DATA__,
    // presumably at the same path (Team Duels likely shares the same
    // server-side data structure as Duels). If that weren't the case,
    // the list would just stay empty and the exact path would need
    // checking.
    function extraireManchesTeamDuels() {
      try {
        const scriptEl = document.getElementById('__NEXT_DATA__');
        if (!scriptEl) return [];
        const data = JSON.parse(scriptEl.textContent);
        const rounds = data?.props?.pageProps?.game?.rounds;
        if (!Array.isArray(rounds)) return [];
        return rounds
          .filter((r) => typeof r.lat === "number" && typeof r.lng === "number")
          .map((r) => ({ roundNumber: r.roundNumber, lat: r.lat, lng: r.lng }));
      } catch (e) {
        return [];
      }
    }

    // IMPORTANT: see the identical fix in runOnDuelsSummary above — this
    // used to bail out permanently if read too early on SPA navigation.
    // It's now re-read on every DOM mutation instead (see injectLinks
    // below), until data is actually found.
    let roundLocations = extraireManchesTeamDuels();

    const injectedLinks = []; // { link, labelEl }
    const iconesApercu = []; // 🖼️ icons, manage their own positioning
    let premierElementListe = null;

    function positionLink(link, labelEl) {
      // Measure the real width of the displayed TEXT ("Round 3", etc.),
      // not its container element which can be wider (padding, fixed
      // column width...) — same fix as in Challenge mode.
      const range = document.createRange();
      range.selectNodeContents(labelEl);
      const texteRect = range.getBoundingClientRect();
      const labelRect = labelEl.getBoundingClientRect();

      link.style.top = labelRect.top + labelRect.height / 2 + "px";
      link.style.left = texteRect.right + 6 + "px";
    }

    function repositionAllLinks() {
      injectedLinks.forEach(({ link, labelEl }) => {
        positionLink(link, labelEl);
        const visible = estVisibleDansConteneurs(labelEl);
        link.style.display = visible ? "" : "none";
        if (link._iconeMeta) link._iconeMeta.style.display = visible ? "" : "none";
      });
    }

    // The exact class name wrapping the "Round N" text isn't always
    // predictable (and can change between deploys). Rather than relying
    // on a generated CSS class, we search directly, in each round row,
    // for the "Round N" text — which robustly gives us both the exact
    // element to anchor the icon on AND the round number.
    function trouverLabelRound(row) {
      const walker = document.createTreeWalker(row, NodeFilter.SHOW_TEXT);
      let node;
      while ((node = walker.nextNode())) {
        const texte = node.textContent.trim();
        const match = texte.match(/^Round\s+(\d+)$/i);
        if (match) {
          return { element: node.parentElement, numero: parseInt(match[1], 10) };
        }
      }
      return null;
    }

    function injectLinks() {
      if (roundLocations.length === 0) {
        roundLocations = extraireManchesTeamDuels(); // retry: __NEXT_DATA__ may not have been ready yet
        if (roundLocations.length === 0) return; // still nothing, wait for the next DOM mutation
      }

      const rows = document.querySelectorAll('[class*="game-summary_playedRound__"]');

      rows.forEach((row) => {
        if (!premierElementListe) premierElementListe = row;
        if (row.dataset.cartometaInjected) return;

        const resultat = trouverLabelRound(row);
        if (!resultat) return;

        const loc = roundLocations.find((r) => r.roundNumber === resultat.numero);
        if (!loc) return;

        const link = document.createElement("a");
        link.href = buildCartometaUrl(loc.lat, loc.lng);
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.innerHTML = '<svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>';
        link.style.color = "#fff";
        link.style.filter = "drop-shadow(0 1px 3px rgba(0,0,0,0.9))";
        link.title = "Open on Cartometa";
        link.style.position = "fixed";
        link.style.display = "inline-flex";
        link.style.transform = "translateY(-50%)";
        link.style.textDecoration = "none";
        link.style.cursor = "pointer";
        link.style.zIndex = "999999";
        link.style.pointerEvents = "auto";

        document.body.appendChild(link);
        positionLink(link, resultat.element);
        injectedLinks.push({ link, labelEl: resultat.element });

        const iconeApercuTeamDuels = ajouterIconeApercu(link, loc.lat, loc.lng);
        link._iconeMeta = iconeApercuTeamDuels;
        iconesApercu.push(iconeApercuTeamDuels);

        row.dataset.cartometaInjected = "true";
        // IMPORTANT: the grace period below (estVisibleDansConteneurs)
        // reads this timestamp off `labelEl`, NOT `row` — they're two
        // different elements here. Setting it on the wrong one silently
        // disabled the grace period entirely, causing a visibility
        // flicker on every round except the first as the row's entrance
        // animation was still settling.
        resultat.element.dataset.cartometaInjectedAt = String(Date.now());
      });

      if (premierElementListe && roundLocations.length > 0) {
        const tousLesRounds = roundLocations.map((r) => ({
          roundNumber: r.roundNumber,
          lat: r.lat,
          lng: r.lng,
          flagSrc: null,
        }));
        ajouterBoutonAuDessusListe(premierElementListe, tousLesRounds, "cartometa-bouton-liste-team-duels", true);
      }
    }

    window.addEventListener("resize", repositionAllLinks);
    window.addEventListener("scroll", repositionAllLinks, true);

    const observer = new MutationObserver(
      grouperParFrame(() => {
        if (maGeneration !== generationActuelle) {
          observer.disconnect();
          return;
        }
        injectLinks();
        repositionAllLinks();
      })
    );

    observer.observe(document.body, { childList: true, subtree: true });

    surveillerNavigation(
      () => premierElementListe,
      () => {
        injectedLinks.forEach(({ link }) => link.remove());
        iconesApercu.forEach((icone) => icone.remove());
        const bouton = document.getElementById("cartometa-bouton-liste-team-duels");
        if (bouton) bouton.remove();
        observer.disconnect();
        window.removeEventListener("resize", repositionAllLinks);
        window.removeEventListener("scroll", repositionAllLinks, true);
      }
    );
  }

  // ---- 1.2c Challenge results screen (Challenge Highscore) ----
  // ---- 1.2d Live Challenge (Party mode) "Game breakdown" screen ----
  // Shows a per-player leaderboard; clicking a player expands a
  // per-round detail (one row per round, "Round N" label) — that's
  // where the icons go, reusing the coordinates already captured via
  // the live-challenge network interception above (see
  // extractRoundLocationsLiveChallenge).
  // ---- 1.2e Party Duels ("game-summary-2" results screen) ----
  // A newer results screen used for Party-mode Duels, with a
  // completely different layout from the regular Duels summary: each
  // round row shows both players' scores side by side rather than one
  // player's breakdown at a time. Per the request, icons are stacked
  // vertically at the midpoint BETWEEN the two score columns, rather
  // than off to one side.
  function runOnPartyDuels(buildCartometaUrl, maGeneration) {
    const injectedIcons = []; // { link, icone, row } — all three repositioned together
    let premiereLigne = null; // to detect when this page is left

    function centreHorizontalPourRangee(row) {
      const rect = row.getBoundingClientRect();
      const textes = row.querySelectorAll('[class*="game-summary-2_text__"]');
      let centreX = rect.left + rect.width / 2; // fallback: middle of the whole row

      if (textes.length >= 2) {
        // Shifted one column to the left from the very last two: in
        // simple Party Duels there are only 2 columns (one score per
        // player) so those are used directly; Team Duels has extra
        // columns after the pair we actually want (closest guess team
        // 2 / health team 1), so we reach one further back when there
        // are more than 2 to choose from.
        const indexA = textes.length >= 3 ? textes.length - 3 : 0;
        const indexB = textes.length >= 3 ? textes.length - 2 : 1;
        const rectA = textes[indexA].getBoundingClientRect();
        const rectB = textes[indexB].getBoundingClientRect();
        // Midpoint between the inner edges of the two score columns —
        // works regardless of which one is wider or on which side.
        centreX = (Math.min(rectA.right, rectB.right) + Math.max(rectA.left, rectB.left)) / 2;
      }

      return centreX;
    }

    function positionnerPourRangee(link, icone, row) {
      const rect = row.getBoundingClientRect();
      const centreX = centreHorizontalPourRangee(row);
      const centreY = rect.top + rect.height / 2;
      link.style.left = centreX + "px";
      link.style.top = centreY - 6 + "px"; // slightly above center
      icone.style.left = centreX + "px";
      icone.style.top = centreY + 18 + "px"; // slightly below center
    }

    function repositionAllLinks() {
      injectedIcons.forEach(({ link, icone, row }) => {
        positionnerPourRangee(link, icone, row);
        const visible = estVisibleDansConteneurs(row);
        link.style.display = visible ? "" : "none";
        icone.style.display = visible ? "" : "none";
      });
    }

    function injectLinks() {
      const rows = document.querySelectorAll('[class*="game-summary-2_playedRound__"]');
      if (rows.length > 0 && !premiereLigne) premiereLigne = rows[0];

      rows.forEach((row) => {
        if (row.dataset.cartometaInjected) return;

        const numeroEl = row.querySelector('[class*="game-summary-2_roundNumber__"]');
        const numero = numeroEl ? parseInt(numeroEl.textContent.trim(), 10) : NaN;
        if (isNaN(numero)) return;

        const loc = etatPartyDuels.roundLocations[numero];
        if (!loc) return;

        const link = document.createElement("a");
        link.href = buildCartometaUrl(loc.lat, loc.lng);
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.innerHTML =
          '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>';
        link.style.color = "#fff";
        link.style.filter = "drop-shadow(0 1px 3px rgba(0,0,0,0.9))";
        link.title = "Open on Cartometa";
        link.style.position = "fixed";
        link.style.display = "inline-flex";
        link.style.transform = "translate(-50%, -50%)"; // centered exactly on the computed midpoint
        link.style.textDecoration = "none";
        link.style.cursor = "pointer";
        link.style.zIndex = "999999";
        link.style.pointerEvents = "auto";
        document.body.appendChild(link);

        // NOT using the shared ajouterIconeApercu() here: it installs
        // its own resize/scroll listeners that reposition itself to the
        // right of its neighbor link, which would fight with the
        // stacked positioning this mode needs (below the link, not
        // beside it) on every resize/scroll.
        const icone = document.createElement("a");
        icone.href = "javascript:void(0)";
        icone.innerHTML =
          '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>';
        icone.style.color = "#fff";
        icone.style.filter = "drop-shadow(0 1px 3px rgba(0,0,0,0.9))";
        icone.title = "Cartometa metas preview";
        icone.style.position = "fixed";
        icone.style.display = "inline-flex";
        icone.style.transform = "translate(-50%, -50%)";
        icone.style.textDecoration = "none";
        icone.style.cursor = "pointer";
        icone.style.zIndex = "999999";
        icone.style.pointerEvents = "auto";
        icone.addEventListener("click", (e) => {
          e.preventDefault();
          ouvrirApercuMetas(loc.lat, loc.lng);
        });
        document.body.appendChild(icone);

        positionnerPourRangee(link, icone, row);
        injectedIcons.push({ link, icone, row });

        row.dataset.cartometaInjected = "true";
        row.dataset.cartometaInjectedAt = String(Date.now());
      });

      // "View all rounds" button, positioned above the first round row
      // and horizontally centered on the exact same point as the
      // per-round icons below it (the midpoint between the two score
      // columns), rather than the generic left-edge alignment used
      // elsewhere.
      const nombreDeRounds = Object.keys(etatPartyDuels.roundLocations).length;
      if (rows.length > 0 && nombreDeRounds > 0 && !document.getElementById("cartometa-bouton-liste-party-duels")) {
        const tousLesRounds = Object.keys(etatPartyDuels.roundLocations)
          .map(Number)
          .sort((a, b) => a - b)
          .map((n) => ({
            roundNumber: n,
            lat: etatPartyDuels.roundLocations[n].lat,
            lng: etatPartyDuels.roundLocations[n].lng,
          }));

        const boutonTous = document.createElement("div");
        boutonTous.id = "cartometa-bouton-liste-party-duels";
        boutonTous.style.display = "flex";
        boutonTous.style.alignItems = "center";
        boutonTous.style.gap = "6px";
        boutonTous.innerHTML =
          '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="3" width="16" height="18" rx="2"/><line x1="8" y1="8" x2="16" y2="8"/><line x1="8" y1="12" x2="16" y2="12"/><line x1="8" y1="16" x2="13" y2="16"/></svg><span>View all rounds</span>';
        boutonTous.title = "View all rounds on Cartometa";
        boutonTous.style.position = "fixed";
        boutonTous.style.padding = "4px 10px";
        boutonTous.style.background = obtenirParametres().couleurAccent;
        boutonTous.style.color = "#111";
        boutonTous.style.fontWeight = "bold";
        boutonTous.style.borderRadius = "14px";
        boutonTous.style.cursor = "pointer";
        boutonTous.style.zIndex = "999999";
        boutonTous.style.boxShadow = "0 2px 8px rgba(0,0,0,0.4)";
        boutonTous.style.fontSize = "13px";
        boutonTous.style.whiteSpace = "nowrap";
        boutonTous.style.transform = "translate(-50%, -100%)"; // centered horizontally, sitting just above the point
        boutonTous.addEventListener("click", () => {
          window.open(buildCartometaBatchUrl(tousLesRounds), "_blank");
        });
        document.body.appendChild(boutonTous);

        function positionnerBoutonTous() {
          const rectPremiere = rows[0].getBoundingClientRect();
          boutonTous.style.left = centreHorizontalPourRangee(rows[0]) + "px";
          boutonTous.style.top = rectPremiere.top - 8 + "px";
        }
        positionnerBoutonTous();
        window.addEventListener("resize", positionnerBoutonTous);
        // Deliberately fixed: no scroll tracking, unlike the per-round
        // icons below it — this button stays put once positioned.
      }
    }

    window.addEventListener("resize", repositionAllLinks);
    window.addEventListener("scroll", repositionAllLinks, true);

    const observer = new MutationObserver(
      grouperParFrame(() => {
        if (maGeneration !== generationActuelle) {
          observer.disconnect();
          return;
        }
        injectLinks();
        repositionAllLinks();
      })
    );

    observer.observe(document.body, { childList: true, subtree: true });

    surveillerNavigation(
      () => premiereLigne,
      () => {
        injectedIcons.forEach(({ link, icone }) => {
          link.remove();
          icone.remove();
        });
        injectedIcons.length = 0;
        window.removeEventListener("resize", repositionAllLinks);
        window.removeEventListener("scroll", repositionAllLinks, true);
        const boutonTousExistant = document.getElementById("cartometa-bouton-liste-party-duels");
        if (boutonTousExistant) boutonTousExistant.remove();
        observer.disconnect();
      }
    );

    injectLinks();
    repositionAllLinks();
  }

  function runOnLiveChallenge(buildCartometaUrl, maGeneration) {
    const injectedLinks = []; // { link, row }
    const iconesApercu = []; // 🖼️ icons, manage their own positioning
    let premiereLigne = null; // to detect when this page is left

    function positionLink(link, row) {
      const rect = row.getBoundingClientRect();
      link.style.top = rect.top + rect.height / 2 + "px";
      link.style.left = rect.right + 8 + "px";
    }

    function repositionAllLinks() {
      injectedLinks.forEach(({ link, row }) => {
        positionLink(link, row);
        const visible = estVisibleDansConteneurs(row);
        link.style.display = visible ? "" : "none";
        if (link._iconeMeta) link._iconeMeta.style.display = visible ? "" : "none";
      });
    }

    function injectLinks() {
      const labels = document.querySelectorAll('[class*="styles_roundLabel__"]');
      if (labels.length > 0 && !premiereLigne) premiereLigne = labels[0];

      labels.forEach((label) => {
        if (label.dataset.cartometaInjected) return;

        // The label's text is "Round " + the number, possibly split
        // across separate text nodes by React — read the combined text
        // rather than relying on a single node.
        const texte = label.textContent.trim();
        const correspondance = texte.match(/(\d+)/);
        if (!correspondance) return;
        const numero = parseInt(correspondance[1], 10);

        const loc = etatLiveChallenge.roundLocations[numero];
        if (!loc) return;

        const link = document.createElement("a");
        link.href = buildCartometaUrl(loc.lat, loc.lng);
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.innerHTML =
          '<svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>';
        link.style.color = "#fff";
        link.style.filter = "drop-shadow(0 1px 3px rgba(0,0,0,0.9))";
        link.title = "Open on Cartometa";
        link.style.position = "fixed";
        link.style.display = "inline-flex";
        link.style.transform = "translateY(-50%)";
        link.style.textDecoration = "none";
        link.style.cursor = "pointer";
        link.style.zIndex = "999999";
        link.style.pointerEvents = "auto";

        document.body.appendChild(link);
        positionLink(link, label);
        injectedLinks.push({ link, row: label });

        const iconeApercuLC = ajouterIconeApercu(link, loc.lat, loc.lng);
        link._iconeMeta = iconeApercuLC;
        iconesApercu.push(iconeApercuLC);

        label.dataset.cartometaInjected = "true";
        label.dataset.cartometaInjectedAt = String(Date.now());
      });
    }

    window.addEventListener("resize", repositionAllLinks);
    window.addEventListener("scroll", repositionAllLinks, true);

    const observer = new MutationObserver(
      grouperParFrame(() => {
        if (maGeneration !== generationActuelle) {
          observer.disconnect();
          return;
        }
        injectLinks();
        repositionAllLinks();
      })
    );

    observer.observe(document.body, { childList: true, subtree: true });

    surveillerNavigation(
      () => premiereLigne,
      () => {
        injectedLinks.forEach(({ link }) => link.remove());
        injectedLinks.length = 0;
        iconesApercu.forEach((icone) => icone.remove());
        iconesApercu.length = 0;
        window.removeEventListener("resize", repositionAllLinks);
        window.removeEventListener("scroll", repositionAllLinks, true);
        observer.disconnect();
      }
    );

    injectLinks();
    repositionAllLinks();
  }

  function runOnChallengeResults(buildCartometaUrl, maGeneration) {
    // Here too, coordinates are already available in the page's Next.js
    // data, accessible directly as a JavaScript object via
    // window.__NEXT_DATA__ (no need to re-parse JSON text, avoiding the
    // truncation issues seen when testing from the console).
    function extraireManchesChallenge() {
      try {
        const rounds = window.__NEXT_DATA__?.props?.pageProps?.rounds;
        if (!Array.isArray(rounds)) return [];
        return rounds
          .filter((r) => typeof r.lat === "number" && typeof r.lng === "number")
          .map((r) => ({ lat: r.lat, lng: r.lng }));
      } catch (e) {
        return [];
      }
    }

    // IMPORTANT: see the identical fix in runOnDuelsSummary above — this
    // used to bail out permanently if read too early on SPA navigation.
    // It's now re-read on every DOM mutation instead (see injectLinks
    // below), until data is actually found.
    let roundLocations = extraireManchesChallenge();

    const injectedLinks = []; // { link, header }
    const iconesApercu = []; // 🖼️ icons, manage their own positioning
    let ligneEnTeteTrouvee = null; // to detect when this page is left

    function positionLink(link, header) {
      // Measure the real width AND height of the displayed TEXT
      // ("ROUND 2", etc.), not the element wrapping it: this gives a
      // more precise vertical alignment (underlined text often has extra
      // space below it because of the "underline" style, which throws
      // off the center if based on the whole element).
      const range = document.createRange();
      range.selectNodeContents(header);
      const texteRect = range.getBoundingClientRect();

      link.style.top = texteRect.top + texteRect.height / 2 + "px";
      link.style.left = texteRect.right + 4 + "px";
    }

    function repositionAllLinks() {
      injectedLinks.forEach(({ link, header }) => {
        positionLink(link, header);
        const visible = estVisibleDansConteneurs(header);
        link.style.display = visible ? "" : "none";
        if (link._iconeMeta) link._iconeMeta.style.display = visible ? "" : "none";
      });
    }

    // The "ROUND 1", "ROUND 2"... headers are clickable columns
    // (probably to sort the table by round): we use the same "fixed"
    // positioning technique anchored outside the table's DOM, to never
    // interfere with that sort click, rather than inserting the icon
    // inside the column itself.
    // GeoGuessr changed this table's structure: there are no longer
    // separate clickable-column divs, everything is grouped into a
    // single header row ("coordinate-results_headerRow__..."). Also,
    // the "ROUND N" text is likely split across several text nodes by
    // React (e.g. "ROUND " and "1" separately), so we compare each
    // element's COMBINED text instead of a single text node, and always
    // keep the most precise (shortest) match for a tight anchor to the
    // displayed text.
    function trouverEnTetesRounds() {
      const headerRow = document.querySelector('[class*="coordinate-results_headerRow__"]');
      if (headerRow && !ligneEnTeteTrouvee) ligneEnTeteTrouvee = headerRow;
      if (!headerRow) return { rounds: [], totalEl: null };

      const candidatsRound = new Map(); // numero -> most precise element found
      let totalEl = null;

      headerRow.querySelectorAll("*").forEach((el) => {
        const texte = el.textContent.replace(/\s+/g, " ").trim();
        const matchRound = texte.match(/^ROUND\s+(\d+)$/i);
        if (matchRound) {
          const numero = parseInt(matchRound[1], 10);
          const actuel = candidatsRound.get(numero);
          // <= (not <): in case of a text-length tie between a parent
          // and its direct child (parent with no other content), keep
          // the LAST one found, i.e. the deepest in the DOM
          // (querySelectorAll always lists a parent before its children).
          if (!actuel || el.textContent.length <= actuel.textContent.length) {
            candidatsRound.set(numero, el);
          }
        } else if (/^total$/i.test(texte)) {
          if (!totalEl || el.textContent.length <= totalEl.textContent.length) {
            totalEl = el;
          }
        }
      });

      const rounds = Array.from(candidatsRound.entries()).map(([numero, element]) => ({
        element,
        numero,
      }));
      return { rounds, totalEl };
    }

    function injectLinks() {
      if (roundLocations.length === 0) {
        roundLocations = extraireManchesChallenge(); // retry: __NEXT_DATA__ may not have been ready yet
        if (roundLocations.length === 0) return; // still nothing, wait for the next DOM mutation
      }

      const { rounds: entetesRounds, totalEl: totalHeader } = trouverEnTetesRounds();

      entetesRounds.forEach(({ element: header, numero }) => {
        if (header.dataset.cartometaInjected) return;

        const loc = roundLocations[numero - 1];
        if (!loc) return;

        const link = document.createElement("a");
        link.href = buildCartometaUrl(loc.lat, loc.lng);
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>';
        link.style.color = "#fff";
        link.style.filter = "drop-shadow(0 1px 3px rgba(0,0,0,0.9))";
        link.title = "Open on Cartometa";
        link.style.position = "fixed";
        link.style.display = "inline-flex";
        link.style.transform = "translateY(-50%)";
        link.style.textDecoration = "none";
        link.style.cursor = "pointer";
        link.style.zIndex = "999999";
        link.style.pointerEvents = "auto";

        document.body.appendChild(link);
        positionLink(link, header);
        injectedLinks.push({ link, header });

        const iconeApercuChallenge = ajouterIconeApercu(link, loc.lat, loc.lng);
        link._iconeMeta = iconeApercuChallenge;
        iconesApercu.push(iconeApercuChallenge);

        header.dataset.cartometaInjected = "true";
        header.dataset.cartometaInjectedAt = String(Date.now());
      });

      if (totalHeader && roundLocations.length > 0) {
        const tousLesRounds = roundLocations.map((loc, i) => ({
          roundNumber: i + 1,
          lat: loc.lat,
          lng: loc.lng,
          flagSrc: null,
        }));
        ajouterBoutonTousLesRounds(totalHeader, tousLesRounds, "cartometa-bouton-total-challenge");
      }
    }

    window.addEventListener("resize", repositionAllLinks);
    window.addEventListener("scroll", repositionAllLinks, true);

    const observer = new MutationObserver(
      grouperParFrame(() => {
        if (maGeneration !== generationActuelle) {
          observer.disconnect();
          return;
        }
        injectLinks();
        repositionAllLinks();
      })
    );

    observer.observe(document.body, { childList: true, subtree: true });

    surveillerNavigation(
      () => ligneEnTeteTrouvee,
      () => {
        injectedLinks.forEach(({ link }) => link.remove());
        iconesApercu.forEach((icone) => icone.remove());
        const boutonTotal = document.getElementById("cartometa-bouton-total-challenge");
        if (boutonTotal) boutonTotal.remove();
        observer.disconnect();
        window.removeEventListener("resize", repositionAllLinks);
        window.removeEventListener("scroll", repositionAllLinks, true);
      }
    );
  }

  // =========================================================
  // PARTIE 2 — Cartometa : clic automatique + panneau tous les rounds
  // =========================================================
  function runOnCartometa() {
    // Cartometa already fetches a per-country JSON file (containing
    // each meta's title/description/source_url/etc., keyed by a short
    // id) whenever a point is clicked — we've seen its shape directly
    // via the Network tab. Rather than duplicating that request
    // ourselves (which would be wasteful and add latency), we intercept
    // the SAME fetch Cartometa already makes, and index it by
    // thumbnail filename — the one piece of data we can reliably match
    // against what's already visible in each scraped <article>.
    const infosParVignette = new Map(); // thumbnail filename -> { sourceUrl, category }

    function traiterReponseDonneesPays(data) {
      if (!data || !data.metas) {
        console.log("[GeoGuessr→Cartometa] Country data response has no .metas field:", data);
        return;
      }
      for (const cle of Object.keys(data.metas)) {
        const meta = data.metas[cle];
        if (meta && meta.thumb) {
          infosParVignette.set(meta.thumb, {
            sourceUrl: meta.source_url || null,
            category: meta.category || null,
          });
        }
      }
      console.log(
        "[GeoGuessr→Cartometa] Meta info captured for",
        infosParVignette.size,
        "thumbnails:",
        infosParVignette
      );
    }

    function estRequeteDonneesPays(url) {
      return typeof url === "string" && url.includes("data/h/c/");
    }

    try {
      const originalFetch = window.fetch;
      window.fetch = function (...args) {
        const promesse = originalFetch.apply(this, args);
        try {
          let url = null;
          if (typeof args[0] === "string") url = args[0];
          else if (args[0] instanceof URL) url = args[0].href;
          else if (args[0] && typeof args[0].url === "string") url = args[0].url;

          if (estRequeteDonneesPays(url)) {
            promesse
              .then((response) => response.clone().json())
              .then(traiterReponseDonneesPays)
              .catch((e) => console.log("[GeoGuessr→Cartometa] Error parsing country data JSON:", e));
          }
        } catch (e) {
          // never block the original fetch on error
        }
        return promesse;
      };

      const originalOpen = XMLHttpRequest.prototype.open;
      XMLHttpRequest.prototype.open = function (method, url, ...reste) {
        if (estRequeteDonneesPays(url)) {
          this.addEventListener("load", () => {
            try {
              traiterReponseDonneesPays(JSON.parse(this.responseText));
            } catch (e) {
              // ignore silently (non-JSON response, etc.)
            }
          });
        }
        return originalOpen.call(this, method, url, ...reste);
      };
    } catch (e) {
      console.log("[GeoGuessr→Cartometa] Failed to install source URL interception:", e);
    }

    // Matches a scraped <img> (a meta's thumbnail) against the
    // per-country data captured above, by filename — the thumbnail
    // paths in that JSON are relative ("PK/0iLc.t.e0e4e143.webp"),
    // while img.src is absolute, so we compare by filename rather than
    // requiring an exact match.
    function trouverInfosVignette(img) {
      if (!img) return { sourceUrl: null, category: null };
      const nomFichier = img.src.split("/").pop().split("?")[0];
      for (const [cheminRelatif, infos] of infosParVignette) {
        if (cheminRelatif.endsWith(nomFichier)) return infos;
      }
      console.log(
        "[GeoGuessr→Cartometa] No metadata match for filename:",
        nomFichier,
        "— known thumbnails:",
        [...infosParVignette.keys()]
      );
      return { sourceUrl: null, category: null };
    }

    // The map already centers on the point targeted by the URL hash
    // (#lat,lng,zoom) on load. So there's no need to compute the point's
    // pixel position: the CENTER of the map container matches that
    // point exactly.
    function simulerClicCentral() {
      const carte = document.getElementById('carte');
      if (!carte) return false;

      const rect = carte.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return false; // pas encore rendue

      const x = rect.left + rect.width / 2;
      const y = rect.top + rect.height / 2;

      const options = {
        bubbles: true,
        cancelable: true,
        view: window,
        clientX: x,
        clientY: y,
      };

      // Send the full sequence (mousedown/mouseup/click): Leaflet
      // usually listens to the native "click" event directly, but also
      // sending mousedown/mouseup beforehand makes triggering it safer
      // in case the site distinguishes a click from a drag.
      carte.dispatchEvent(new MouseEvent('mousedown', options));
      carte.dispatchEvent(new MouseEvent('mouseup', options));
      carte.dispatchEvent(new MouseEvent('click', options));

      return true;
    }

    // L'initialisation de Leaflet (et le rendu du conteneur) est
    // asynchronous: we retry at short intervals until the
    // click could be sent, with a cap so it doesn't loop forever if the
    // map never appears (homepage with no hash, for instance). Reusable
    // function: it needs to be re-triggerable on every hash change (see
    // below), not just on the very first page load.
    function tenterClicCentral() {
      let tentatives = 0;
      const MAX_TENTATIVES = 33; // ~5 seconds at 150ms intervals

      const intervalId = setInterval(() => {
        tentatives += 1;
        const succes = simulerClicCentral();
        if (succes || tentatives >= MAX_TENTATIVES) {
          clearInterval(intervalId);
        }
      }, 150);
    }

    function hashEstUneListeDeRounds() {
      return location.hash.indexOf('#rounds=') === 0;
    }

    function hashEstUnApercu() {
      return new URLSearchParams(location.search).has("cartometaPreview");
    }

    // "Preview" mode: opened by the small 🖼️ icon on GeoGuessr, via a
    // background popup. The hash stays in the standard format
    // (#lat,lng,zoom) — that's what normally centers the map, just like
    // any regular Cartometa link. Only the request id (needed to know
    // who to send the response to) travels through the
    // ?cartometaPreview=... query parameter, separate from the hash. We
    // auto-click the point (as usual), wait for metas to appear, extract
    // the first ones (image + text), send them back to the window that
    // opened us via postMessage, then close ourselves.
    // Simulates a hover on a meta card to trigger its footprint being
    // highlighted on cartometa.com's own map — which internally calls
    // L.geoJSON(footprint, ...). We temporarily intercept that function
    // (already loaded by the site itself, no need to load Leaflet
    // ourselves) to grab the footprint as it goes by, without ever
    // needing to know the internal format cartometa.com uses to
    // associate a meta with its geometry (variable names, data
    // structure...).
    function extraireGeometrie(article) {
      if (typeof window.L === "undefined" || !window.L.geoJSON) return null;

      let geometrieCapturee = null;
      const original = window.L.geoJSON;
      window.L.geoJSON = function (data, options) {
        geometrieCapturee = data;
        return original.apply(this, arguments);
      };

      try {
        article.dispatchEvent(
          new MouseEvent("mouseenter", { bubbles: true, cancelable: true, view: window })
        );
      } catch (e) {
        // nothing serious, we'll just return null for this meta
      }

      window.L.geoJSON = original; // always restore, even if the above failed
      return geometrieCapturee;
    }

    function traiterApercu() {
      const parametresURL = new URLSearchParams(location.search);
      const requestId = parametresURL.get("cartometaPreview");
      if (!requestId) {
        window.close();
        return;
      }
      const nombreMetas = parseInt(parametresURL.get("metaCount"), 10) || 6;

      let tentatives = 0;
      const MAX_TENTATIVES = 33; // ~5 seconds at 150ms intervals
      const intervalId = setInterval(() => {
        tentatives += 1;
        const articles = document.querySelectorAll('article.carte-meta');

        // Keep re-clicking until metas actually appear: the very first
        // click can land too early (before Leaflet finishes
        // initializing and wiring up its own listeners), with no
        // reliable way to detect that in advance. Re-clicking the same
        // point is harmless (it just shows the same metas again, like a
        // repeated manual click).
        if (articles.length === 0) {
          simulerClicCentral();
        }

        if (articles.length > 0 || tentatives >= MAX_TENTATIVES) {
          clearInterval(intervalId);

          const metas = Array.from(articles)
            .slice(0, nombreMetas)
            .map((article) => {
              const img = article.querySelector('img');
              const texte = article.querySelector('p');
              const codePaysEl = article.querySelector('.code-pays');

              // The country code span sits INSIDE the paragraph, so its
              // text would otherwise be merged into the description
              // ("FR These forests..."). We clone the paragraph and
              // strip that span out before reading the text, since the
              // code is now shown separately (flag + country name).
              let texteMeta = "";
              if (texte) {
                const clone = texte.cloneNode(true);
                const spanCode = clone.querySelector('.code-pays');
                if (spanCode) spanCode.remove();
                texteMeta = clone.textContent.trim();
              }

              const infosVignette = trouverInfosVignette(img);

              return {
                // img.src (et non getAttribute) donne directement l'URL
                // absolute URL, even if the source HTML has a relative
                // path.
                image: img ? img.src : null,
                texte: texteMeta,
                codePays: codePaysEl ? codePaysEl.textContent.trim() : null,
                sourceUrl: infosVignette.sourceUrl,
                categorie: infosVignette.category,
                geometrie: extraireGeometrie(article),
              };
            });

          try {
            if (window.opener) {
              window.opener.postMessage(
                { type: "cartometa-metas", requestId, metas },
                "https://www.geoguessr.com"
              );
            }
          } catch (e) {
            // nothing more to do if we can't reach the opener window
            // (e.g. closed in the meantime)
          }

          window.close();
        }
      }, 150);
    }

    if (hashEstUnApercu()) {
      traiterApercu();
      return;
    }

    function recupererPayloadDepuisHash() {
      try {
        const brut = decodeURIComponent(location.hash.slice('#rounds='.length));
        const payload = JSON.parse(brut);
        if (payload && Array.isArray(payload.rounds) && payload.rounds.length > 0) {
          return payload;
        }
      } catch (e) {
        // hash invalide ou corrompu, on ignore
      }
      return null;
    }

    // Navigates to a given round: update the hash then force a real
    // reload (see the explanation below on why just changing the hash
    // isn't enough here). Shared between clicking a panel button AND the
    // automatic opening of Round 1 on the very first load. Zoom comes
    // from the user's setting on GeoGuessr (passed via the payload, see
    // buildCartometaBatchUrl) — defaults to 11 if absent.
    function allerAuRound(round, zoom) {
      const zoomAUtiliser = zoom || 11;
      location.hash = `${round.lat.toFixed(4)},${round.lng.toFixed(4)},${zoomAUtiliser}`;
      location.reload();
    }

    // cartometa.com ne lit le hash de l'URL qu'AU CHARGEMENT de la page
    // (no live-update logic like "hashchange"): just changing the hash
    // without reloading moves neither the map nor the zoom. To navigate
    // from one round to another,
    // a real reload is required — exactly like the first click on a
    // Cartometa link from GeoGuessr, which already works fine.
    //
    // For the "all rounds" panel to survive this reload, the full
    // payload (rounds + zoom + color) is saved in the browser's
    // sessionStorage (scoped to this tab, no special Tampermonkey
    // permission needed), and re-read on every page load.
    if (hashEstUneListeDeRounds()) {
      const payload = recupererPayloadDepuisHash();
      if (payload) {
        try {
          sessionStorage.setItem('cartometaRoundsPanel', JSON.stringify(payload));
        } catch (e) {
          // sessionStorage unavailable (strict private browsing, etc.):
          // the panel will still work for this first load,
          // it just won't survive a full reload.
        }
        // Open Round 1 directly by default, instead of waiting for the
        // user to click a button — the panel will reappear right after
        // (via sessionStorage), with this round already highlighted.
        allerAuRound(payload.rounds[0], payload.zoom);
      }
    } else {
      tenterClicCentral();

      // If we land here after clicking a round from the panel (i.e.
      // after a full reload), rebuild the panel from what was saved.
      try {
        const brut = sessionStorage.getItem('cartometaRoundsPanel');
        if (brut) {
          const payload = JSON.parse(brut);
          if (payload && Array.isArray(payload.rounds) && payload.rounds.length > 0) {
            afficherPanneauRounds(
              payload.rounds,
              (round) => allerAuRound(round, payload.zoom),
              payload.couleur
            );
          }
        }
      } catch (e) {
        // fine if unavailable, the auto-click still works
      }
    }
  }

  // Displays a floating panel with one button per round. Clicking a
  // button forces a full page reload onto the matching coordinates (see
  // the explanation above on why just changing the hash isn't enough).
  function afficherPanneauRounds(rounds, allerAuRound, couleur) {
    if (document.getElementById("cartometa-panneau-rounds")) return; // already shown
    if (!Array.isArray(rounds) || rounds.length === 0) return;
    const couleurAUtiliser = couleur || "#5EBF82";

    // Determines the currently displayed round by comparing the
    // current hash's coordinates (#lat,lng,zoom) to each round's, to
    // highlight it in the list.
    function roundEstActif(round) {
      const brut = location.hash.replace(/^#/, "");
      const parties = brut.split(",");
      if (parties.length < 2) return false;
      return (
        parties[0] === round.lat.toFixed(4) &&
        parties[1] === round.lng.toFixed(4)
      );
    }

    const panneau = document.createElement("div");
    panneau.id = "cartometa-panneau-rounds";
    panneau.style.position = "fixed";
    panneau.style.top = "55px";
    panneau.style.left = "70px"; // offset to avoid overlapping the +/- zoom buttons
    panneau.style.maxHeight = "80vh";
    panneau.style.overflowY = "auto";
    panneau.style.background = "rgba(20,20,20,0.92)";
    panneau.style.borderRadius = "10px";
    panneau.style.padding = "10px";
    panneau.style.zIndex = "999999";
    panneau.style.fontFamily = "sans-serif";
    panneau.style.color = "#fff";
    panneau.style.boxShadow = "0 4px 16px rgba(0,0,0,0.5)";
    panneau.style.minWidth = "160px";

    // Scrollbar style, matched to the panel's dark theme (by default
    // the native scrollbar is white and clashes). Injected once per
    // page.
    if (!document.getElementById("cartometa-styles-panneau-rounds")) {
      const style = document.createElement("style");
      style.id = "cartometa-styles-panneau-rounds";
      style.textContent = `
        #cartometa-panneau-rounds {
          scrollbar-color: #666 #222;
          scrollbar-width: thin;
        }
        #cartometa-panneau-rounds::-webkit-scrollbar {
          width: 8px;
        }
        #cartometa-panneau-rounds::-webkit-scrollbar-track {
          background: #222;
          border-radius: 8px;
        }
        #cartometa-panneau-rounds::-webkit-scrollbar-thumb {
          background: #666;
          border-radius: 8px;
        }
        #cartometa-panneau-rounds::-webkit-scrollbar-thumb:hover {
          background: #888;
        }
      `;
      (document.head || document.documentElement).appendChild(style);
    }

    // If a position was saved (from a previous drag, before the last
    // reload), apply it here instead of the default position (top
    // right).
    try {
      const positionSauvee = sessionStorage.getItem('cartometaPanelPosition');
      if (positionSauvee) {
        const { left, top } = JSON.parse(positionSauvee);
        if (typeof left === "number" && typeof top === "number") {
          panneau.style.left = left + "px";
          panneau.style.top = top + "px";
          panneau.style.right = "auto";
        }
      }
    } catch (e) {
      // fine, the panel keeps its default position
    }

    // Same idea as the panel's position: every round click causes a
    // full page reload (see below), which recreates this panel from
    // scratch — without this, scroll position would jump back to the top
    // on every round change. The actual restore happens further below,
    // once all round buttons are added (before that, there's nothing to
    // scroll).
    panneau.addEventListener("scroll", () => {
      try {
        sessionStorage.setItem('cartometaPanelScroll', String(panneau.scrollTop));
      } catch (e) {
        // pas grave si indisponible
      }
    });

    const enTete = document.createElement("div");
    enTete.style.display = "flex";
    enTete.style.justifyContent = "space-between";
    enTete.style.alignItems = "center";
    enTete.style.marginBottom = "8px";
    enTete.style.cursor = "move"; // signals that this area can be dragged to move the panel
    enTete.style.userSelect = "none";

    const titre = document.createElement("strong");
    titre.textContent = "Rounds";
    titre.style.fontSize = "15px";
    enTete.appendChild(titre);

    const fermer = document.createElement("span");
    fermer.textContent = "✕";
    fermer.title = "Close";
    fermer.style.cursor = "pointer";
    fermer.style.marginLeft = "12px";
    fermer.addEventListener("click", () => {
      try {
        sessionStorage.removeItem('cartometaRoundsPanel');
        sessionStorage.removeItem('cartometaPanelPosition');
        sessionStorage.removeItem('cartometaPanelScroll');
      } catch (e) {
        // rien de grave si indisponible
      }
      panneau.remove();
    });
    enTete.appendChild(fermer);

    panneau.appendChild(enTete);

    // Drag and drop: track the mouse from the header, and switch the
    // panel from "right" (positioned from the right edge) to "left"
    // (positioned from the left edge) for smooth pixel-based movement.
    let enTrainDeGlisser = false;
    let decalageX = 0;
    let decalageY = 0;

    enTete.addEventListener("mousedown", (e) => {
      enTrainDeGlisser = true;
      const rect = panneau.getBoundingClientRect();
      decalageX = e.clientX - rect.left;
      decalageY = e.clientY - rect.top;
      // Lock in the current position as "left/top" before tracking the
      // mouse, to avoid a visual jump.
      panneau.style.left = rect.left + "px";
      panneau.style.top = rect.top + "px";
      panneau.style.right = "auto";
      e.preventDefault();
    });

    document.addEventListener("mousemove", (e) => {
      if (!enTrainDeGlisser) return;
      panneau.style.left = e.clientX - decalageX + "px";
      panneau.style.top = e.clientY - decalageY + "px";
    });

    document.addEventListener("mouseup", () => {
      if (!enTrainDeGlisser) return;
      enTrainDeGlisser = false;
      try {
        const rect = panneau.getBoundingClientRect();
        sessionStorage.setItem(
          'cartometaPanelPosition',
          JSON.stringify({ left: rect.left, top: rect.top })
        );
      } catch (e) {
        // fine if unavailable, position just won't be remembered
      }
    });

    rounds.forEach((round) => {
      const actif = roundEstActif(round);

      const bouton = document.createElement("button");
      bouton.style.display = "flex";
      bouton.style.alignItems = "center";
      bouton.style.gap = "6px";
      bouton.style.width = "100%";
      bouton.style.marginBottom = "4px";
      bouton.style.padding = "6px 10px";
      bouton.style.background = actif ? couleurAUtiliser : "#333";
      bouton.style.color = actif ? "#111" : "#fff";
      bouton.style.fontWeight = actif ? "bold" : "normal";
      bouton.style.border = actif ? "2px solid #fff" : "none";
      bouton.style.borderRadius = "6px";
      bouton.style.cursor = "pointer";
      bouton.style.fontSize = "14px";

      if (round.flagSrc) {
        const img = document.createElement("img");
        img.src = round.flagSrc;
        img.style.width = "18px";
        img.style.height = "12px";
        img.style.objectFit = "cover";
        bouton.appendChild(img);
      }

      const texte = document.createElement("span");
      texte.textContent = `Round ${round.roundNumber}`;
      bouton.appendChild(texte);

      bouton.addEventListener("click", () => {
        allerAuRound(round);
      });

      panneau.appendChild(bouton);
    });

    document.body.appendChild(panneau);

    // Scroll restoration: MUST happen after the buttons above are added
    // (and after being added to the DOM), otherwise there's nothing to
    // scroll yet and it has no effect.
    try {
      const scrollSauve = sessionStorage.getItem('cartometaPanelScroll');
      if (scrollSauve) {
        panneau.scrollTop = parseInt(scrollSauve, 10) || 0;
      }
    } catch (e) {
      // fine, the panel just stays at the top
    }
  }
})();
