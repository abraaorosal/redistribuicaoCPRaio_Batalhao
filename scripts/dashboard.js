window.__CPRAIO_SKIP_LEGACY_DASHBOARD__ = true;

window.CPRaioDashboard = (() => {
  const MUNICIPAL_GEOJSON_FILE = "dados/ceara_municipios.geojson";
  const EFETIVO_JSON_FILE = "dados/efetivo/efetivo_21_03_2026.json";
  const LEGACY_EFETIVO_MARKDOWN_FILE = "dados/efetivo/efetivo_municipio_simplificado.md";
  const FORTALEZA_KEY = "FORTALEZA";
  const ISOLATED_BATTALION_TYPE = "BATALHAO_ISOLADO";

  const OUTPUT_FILES = {
    comparativo: "output/comparativo_cenarios.json",
    estrutura_final: "output/estrutura_sugerida_final.json",
    relatorio: "output/relatorio_analitico.json",
  };

  const PROPOSAL_VIEW = [{ id: "final_recomendado", label: "Proposta Final Consolidada" }];
  const PREFERRED_BATTALION_ORDER = ["FORTALEZA", "CAUCAIA", "RUSSAS", "SOBRAL", "JUAZEIRO DO NORTE"];

  const BATTALION_COLORS = {
    "Caucaia": "#1f77b4",
    "Russas": "#ff7f0e",
    "Sobral": "#2ca02c",
    "Juazeiro do Norte": "#d62728",
    "Quixadá": "#9467bd",
    "Itapipoca": "#17becf",
    "Crateús": "#8c564b",
    "Eusébio": "#e377c2",
    "Horizonte": "#bcbd22",
    Fortaleza: "#9a3412",
  };

  const state = {
    initialized: false,
    loading: false,
    map: null,
    batalhaoLayers: null,
    geoJsonLayer: null,
    lineLayer: null,
    markerLayer: null,
    layerIndex: {},
    municipiosGeoJson: null,
    featureCollection: null,
    efetivoByMunicipio: {},
    raw: {},
    scenarios: {},
    recommendedScenarioId: null,
    activeScenarioId: "final_recomendado",
    activeBatalhao: "Todos",
    selectedMunicipioKey: null,
    activeSideTab: "analitico",
    sidePanelOpen: false,
    sidePanelBound: false,
    viewportBucket: null,
    resizeBound: false,
    fortalezaValidationLogged: false,
    fortalezaMarkerLogged: false,
  };

  function normalizeName(value) {
    return String(value || "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/\s+/g, " ")
      .trim()
      .toUpperCase();
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function toNumber(value) {
    const num = Number(value);
    return Number.isFinite(num) ? num : null;
  }

  function formatKm(value) {
    const num = toNumber(value);
    if (num === null) return "n/d";
    return `${num.toFixed(1).replace(".", ",")} km`;
  }

  function formatMinutes(value) {
    const num = toNumber(value);
    if (num === null) return "n/d";
    return `${num.toFixed(0)} min`;
  }

  function formatPercent(value) {
    const num = toNumber(value);
    if (num === null) return "n/d";
    return `${num.toFixed(1).replace(".", ",")}%`;
  }

  function formatInteger(value) {
    const num = toNumber(value);
    if (num === null) return "0";
    return Math.round(num).toLocaleString("pt-BR");
  }

  function parseBooleanFlag(value) {
    if (typeof value === "boolean") return value;
    if (typeof value === "number") return value !== 0;
    const normalized = normalizeName(value);
    return normalized === "SIM" || normalized === "TRUE" || normalized === "1";
  }

  function parseEfetivoMarkdown(markdown) {
    return String(markdown || "")
      .split(/\r?\n/)
      .reduce((acc, line) => {
        const match = line.trim().match(/^(.*?)\s+[—-]\s+(\d+)\s*$/);
        if (!match) return acc;
        acc[normalizeName(match[1])] = Number(match[2]);
        return acc;
      }, {});
  }

  function parseEfetivoJson(payload) {
    if (!Array.isArray(payload)) return {};
    return payload.reduce((acc, item) => {
      const municipio = item?.municipio;
      if (!municipio) return acc;
      const efetivo = toNumber(item?.efetivo);
      acc[normalizeName(municipio)] = efetivo === null ? 0 : efetivo;
      return acc;
    }, {});
  }

  function formatStatusLabel(value) {
    const normalized = normalizeName(value).replace(/_/g, " ");
    const map = {
      BATALHAO: "Batalhão",
      "BATALHAO ISOLADO": "Batalhão Isolado",
      COMPANHIA: "Companhia",
      "CIA INDEPENDENTE": "Cia Independente",
      PELOTAO: "Pelotão",
      SEDE: "Sede",
      BASE: "Base",
      OUTRO: "Outro",
    };
    return map[normalized] || String(value || "—");
  }

  function getAssignedBatalhao(row) {
    if (!row) return "—";
    return row.batalhao_sugerido || row.batalhao_cenario || row.batalhao_atual || "—";
  }

  function getSuggestedStatus(row) {
    if (!row) return "—";
    return row.status_sugerido || row.status_sugerido_pre_hierarquia || row.status_atual || "—";
  }

  function getTargetDistance(row) {
    if (!row) return null;
    return toNumber(
      row.distancia_rodoviaria_ao_batalhao_sugerido_km ?? row.distancia_rodoviaria_ao_batalhao_cenario_km,
    );
  }

  function getCurrentDistance(row) {
    if (!row) return null;
    return toNumber(row.distancia_rodoviaria_ao_batalhao_atual_km);
  }

  function getGain(row) {
    if (!row) return null;
    return toNumber(row.ganho_km);
  }

  function isRedistributed(row) {
    return parseBooleanFlag(row?.mudar_batalhao);
  }

  function getMunicipioEfetivo(municipio) {
    return state.efetivoByMunicipio[normalizeName(municipio)] || 0;
  }

  function getRowsEfetivoTotal(rows) {
    return rows.reduce((acc, row) => acc + getMunicipioEfetivo(row?.municipio), 0);
  }

  function getRowsEfetivoRealocado(rows) {
    return rows.reduce((acc, row) => acc + (isRedistributed(row) ? getMunicipioEfetivo(row?.municipio) : 0), 0);
  }

  function isFortalezaName(value) {
    return normalizeName(value) === FORTALEZA_KEY;
  }

  function isIsolatedRow(row) {
    return Boolean(row?.is_fortaleza) || normalizeName(row?.tipo_especial) === ISOLATED_BATTALION_TYPE || isFortalezaName(row?.municipio);
  }

  function getBattalionColor(name) {
    return BATTALION_COLORS[name] || "#4f6d7a";
  }

  function compareBattalionNames(a, b) {
    const aKey = normalizeName(a);
    const bKey = normalizeName(b);
    const aRank = PREFERRED_BATTALION_ORDER.indexOf(aKey);
    const bRank = PREFERRED_BATTALION_ORDER.indexOf(bKey);

    if (aRank !== -1 || bRank !== -1) {
      if (aRank === -1) return 1;
      if (bRank === -1) return -1;
      if (aRank !== bRank) return aRank - bRank;
    }

    return String(a || "").localeCompare(String(b || ""), "pt-BR");
  }

  function sortBattalionNames(names) {
    return [...new Set((names || []).filter(Boolean))].sort(compareBattalionNames);
  }

  function sortBattalionStructures(items) {
    return [...(items || [])].sort((a, b) => compareBattalionNames(a?.batalhao, b?.batalhao));
  }

  function hexToRgb(hex) {
    const normalized = String(hex || "").replace("#", "");
    if (normalized.length !== 6) return null;
    return {
      r: parseInt(normalized.slice(0, 2), 16),
      g: parseInt(normalized.slice(2, 4), 16),
      b: parseInt(normalized.slice(4, 6), 16),
    };
  }

  function rgba(hex, alpha) {
    const rgb = hexToRgb(hex);
    if (!rgb) return hex;
    return `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, ${alpha})`;
  }

  function blendColor(hex, amount) {
    const rgb = hexToRgb(hex);
    if (!rgb) return hex;
    const mix = (value) => {
      const target = amount >= 0 ? 255 : 0;
      const ratio = Math.abs(amount);
      return Math.round(value + (target - value) * ratio);
    };
    return `rgb(${mix(rgb.r)}, ${mix(rgb.g)}, ${mix(rgb.b)})`;
  }

  function getStructureToneColor(baseColor, texture) {
    if (texture === "batalhao") return blendColor(baseColor, -0.06);
    if (texture === "companhia") return blendColor(baseColor, 0.18);
    return blendColor(baseColor, 0.34);
  }

  function getStructureAccentColor(baseColor, texture) {
    const toneColor = getStructureToneColor(baseColor, texture);
    return texture === "batalhao" ? blendColor(toneColor, -0.28) : blendColor(toneColor, -0.36);
  }

  function getTextureType(row) {
    if (!row) return "pelotao";
    if (isIsolatedRow(row)) return "batalhao";
    const battalion = getAssignedBatalhao(row);
    const status = normalizeName(getSuggestedStatus(row));
    if (row.municipio === battalion || status === "BATALHAO") return "batalhao";
    if (status === "COMPANHIA" || status === "CIA_INDEPENDENTE") return "companhia";
    return "pelotao";
  }

  function getFeatureMunicipioName(feature) {
    return String(feature?.properties?.name || feature?.properties?.description || "").trim();
  }

  function getRowForFeature(feature) {
    const scenario = getActiveScenario();
    if (!scenario) return null;
    const municipio = getFeatureMunicipioName(feature);
    if (!municipio) return null;
    return scenario.rowsByKey[normalizeName(municipio)] || null;
  }

  function hydrateFeatureProperties(feature, row) {
    if (!feature?.properties || !row) return;
    feature.properties.cpraio_polo = getAssignedBatalhao(row);
    feature.properties.cpraio_tipo_unidade = formatStatusLabel(getSuggestedStatus(row));
    feature.properties.cpraio_distancia_km = getTargetDistance(row);
    feature.properties.cpraio_tipo_especial = row.tipo_especial || null;
  }

  function styleBatalhao(feature, options = {}) {
    const { visible = true } = options;
    // O GeoJSON original só expõe `name`, `id` e `description`; polo e hierarquia
    // são derivados pela malha operacional atual a partir do nome do município.
    const row = getRowForFeature(feature);
    if (row) {
      hydrateFeatureProperties(feature, row);
    } else if (feature?.properties) {
      feature.properties.cpraio_polo = null;
      feature.properties.cpraio_tipo_unidade = null;
      feature.properties.cpraio_distancia_km = null;
    }

    const polo = feature?.properties?.cpraio_polo || null;
    const rawTipoUnidade = feature?.properties?.cpraio_tipo_unidade || (row ? getSuggestedStatus(row) : "");
    const tipoUnidade = normalizeName(rawTipoUnidade);
    if (!row || !polo || polo === "—") {
      return {
        color: visible ? "#8b99a6" : "#d4dee6",
        weight: visible ? 1.1 : 0.8,
        opacity: visible ? 0.55 : 0.18,
        fillColor: "#e5ebf0",
        fillOpacity: visible ? 0.18 : 0.06,
        dashArray: null,
        className: "",
      };
    }

    const baseColor = getBattalionColor(polo);
    const isIsolated = isIsolatedRow(row);
    const isBatalhao = tipoUnidade === "BATALHAO" || normalizeName(getFeatureMunicipioName(feature)) === normalizeName(polo);
    const isCompanhia = tipoUnidade === "COMPANHIA" || tipoUnidade === "CIA INDEPENDENTE";
    const fillOpacity = !visible ? 0.08 : isIsolated ? 0.82 : isBatalhao ? 0.9 : isCompanhia ? 0.6 : 0.3;
    const weight = !visible ? 1 : isIsolated ? 5.2 : isBatalhao ? 4.8 : isCompanhia ? 2.9 : 2.1;
    const fillColor = baseColor;
    const borderColor = isIsolated
      ? blendColor(baseColor, -0.44)
      : isBatalhao
        ? blendColor(baseColor, -0.34)
        : blendColor(baseColor, -0.46);

    return {
      color: !visible ? "#d4dee6" : borderColor,
      weight,
      opacity: !visible ? 0.18 : 0.98,
      fillColor,
      fillOpacity,
      dashArray: !visible ? null : isIsolated ? "14 4 3 4" : null,
      className: [row?.mudar_batalhao ? "municipio-redistribuido" : "", isIsolated ? "municipio-batalhao-isolado" : ""]
        .filter(Boolean)
        .join(" "),
    };
  }

  function focusBatalhao(batalhao) {
    if (!batalhao) return;
    state.activeBatalhao = batalhao;
    state.selectedMunicipioKey = null;
    render();
    fitBoundsForRows(getFilteredRows());
  }

  function selectMunicipio(row) {
    if (!row?.municipio) return;
    state.selectedMunicipioKey = normalizeName(row.municipio);
    render();
  }

  function clearSelectedMunicipio() {
    if (!state.selectedMunicipioKey) return;
    state.selectedMunicipioKey = null;
    render();
  }

  function refreshMapViewport() {
    if (!state.map) return;
    window.setTimeout(() => {
      state.map.invalidateSize();
      fitBoundsForRows(getFilteredRows());
    }, 180);
  }

  function getViewportBucket() {
    if (window.innerWidth <= 780) return "mobile";
    if (window.innerWidth <= 1250) return "tablet";
    return "desktop";
  }

  function syncResponsiveState() {
    const nextBucket = getViewportBucket();
    if (state.viewportBucket === nextBucket) return false;
    state.viewportBucket = nextBucket;
    state.sidePanelOpen = nextBucket !== "desktop";
    return true;
  }

  function setText(id, value) {
    const node = document.getElementById(id);
    if (node) node.textContent = value;
  }

  function getById(id) {
    return document.getElementById(id);
  }

  function renderSidePanelShell() {
    const panel = getById("side-panel");
    if (!panel) return;
    panel.classList.toggle("is-open", state.sidePanelOpen);
    panel.classList.toggle("is-collapsed", !state.sidePanelOpen);

    const toggleButton = getById("side-panel-toggle");
    const toggleIcon = getById("side-panel-toggle-icon");
    if (toggleButton && toggleIcon) {
      toggleButton.title = state.sidePanelOpen ? "Recolher painel analítico" : "Abrir painel analítico";
      toggleIcon.className = `fa-solid ${state.sidePanelOpen ? "fa-chevron-right" : "fa-chevron-left"}`;
    }

    panel.querySelectorAll("[data-side-tab]").forEach((button) => {
      const active = button.dataset.sideTab === state.activeSideTab;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });

    panel.querySelectorAll("[data-side-section]").forEach((section) => {
      section.classList.toggle("is-active", section.dataset.sideSection === state.activeSideTab);
    });
  }

  function bindSidePanelControls() {
    if (state.sidePanelBound) return;
    const panel = getById("side-panel");
    if (!panel) return;

    panel.querySelectorAll("[data-side-tab]").forEach((button) => {
      button.addEventListener("click", () => {
        const nextTab = button.dataset.sideTab;
        if (!nextTab) return;
        const shouldRefreshMap = !state.sidePanelOpen;
        state.activeSideTab = nextTab;
        state.sidePanelOpen = true;
        renderSidePanelShell();
        if (shouldRefreshMap) refreshMapViewport();
      });
    });

    getById("side-panel-toggle")?.addEventListener("click", () => {
      state.sidePanelOpen = !state.sidePanelOpen;
      renderSidePanelShell();
      refreshMapViewport();
    });

    panel.querySelectorAll("[data-side-close]").forEach((button) => {
      button.addEventListener("click", () => {
        state.sidePanelOpen = false;
        renderSidePanelShell();
        refreshMapViewport();
      });
    });

    state.sidePanelBound = true;
  }

  function bindViewportResize() {
    if (state.resizeBound) return;
    window.addEventListener("resize", () => {
      if (syncResponsiveState()) {
        renderSidePanelShell();
        refreshMapViewport();
      }
    });
    state.resizeBound = true;
  }

  async function fetchJson(url) {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Falha ao carregar ${url}: ${response.status} ${response.statusText}`);
    }
    return response.json();
  }

  async function fetchText(url) {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Falha ao carregar ${url}: ${response.status} ${response.statusText}`);
    }
    return response.text();
  }

  function visitLayers(layer, callback) {
    if (!layer) return;
    const isLeaf = typeof layer.setStyle === "function" || typeof layer.getPopup === "function";
    if (typeof layer.eachLayer === "function" && !isLeaf) {
      layer.eachLayer((child) => visitLayers(child, callback));
      return;
    }
    callback(layer);
  }

  function extractNameFromPopupHtml(html) {
    if (!html) return "";
    const match = String(html).match(/<b>\s*([^<]+?)\s*<\/b>/i);
    return match ? match[1].trim() : "";
  }

  function extractPopupHtml(layer) {
    const popup = layer && typeof layer.getPopup === "function" ? layer.getPopup() : null;
    if (!popup) return "";
    const content = popup.getContent();
    if (typeof content === "string") return content;
    if (content && typeof content.innerHTML === "string") return content.innerHTML;
    return "";
  }

  function extractPopupFields(html) {
    const source = String(html || "")
      .replace(/\n/g, " ")
      .replace(/<\/div>/gi, "")
      .replace(/<div[^>]*>/gi, "");
    const fields = {};
    const pairRegex = /(?:^|<br>\s*)([^:<]+):\s*([^<]+)/gi;
    let match;
    while ((match = pairRegex.exec(source)) !== null) {
      const label = String(match[1] || "").trim();
      const value = String(match[2] || "").trim();
      if (!label || !value) continue;
      fields[label] = value;
    }
    return fields;
  }

  function extractMunicipioName(layer) {
    if (layer?.feature?.properties?.name) {
      return String(layer.feature.properties.name).trim();
    }
    const popup = layer && typeof layer.getPopup === "function" ? layer.getPopup() : null;
    if (popup) {
      return extractNameFromPopupHtml(popup.getContent());
    }
    return "";
  }

  function cloneFeature(feature) {
    if (!feature) return null;
    return JSON.parse(JSON.stringify(feature));
  }

  function rebuildLayerIndexFromGeoJsonLayer(legacyIndex) {
    const index = {};
    if (!state.geoJsonLayer) {
      state.layerIndex = index;
      return;
    }

    state.geoJsonLayer.eachLayer((layer) => {
      const name = extractMunicipioName(layer);
      if (!name) return;
      const key = normalizeName(name);
      index[key] = {
        key,
        name,
        layer,
        legacy: legacyIndex[key]?.legacy || { html: "", fields: {} },
      };
    });

    state.layerIndex = index;
  }

  function buildLayerIndex() {
    // Reaproveita metadados do mapa legado, mas a geometria principal passa a vir da malha oficial do Ceará.
    const legacyIndex = {};
    Object.values(state.batalhaoLayers || {}).forEach((group) => {
      visitLayers(group, (layer) => {
        const name = extractMunicipioName(layer);
        if (!name) return;
        const key = normalizeName(name);
        if (legacyIndex[key]) return;
        const legacyHtml = extractPopupHtml(layer);
        legacyIndex[key] = {
          key,
          name,
          legacy: {
            html: legacyHtml,
            fields: extractPopupFields(legacyHtml),
          },
        };
      });
    });
    const sourceGeoJson = state.municipiosGeoJson || { type: "FeatureCollection", features: [] };
    state.featureCollection = cloneFeature(sourceGeoJson);

    Object.values(state.batalhaoLayers || {}).forEach((group) => {
      if (state.map?.hasLayer(group)) {
        state.map.removeLayer(group);
      }
    });

    if (state.geoJsonLayer && state.map?.hasLayer(state.geoJsonLayer)) {
      state.map.removeLayer(state.geoJsonLayer);
    }

    state.geoJsonLayer = L.geoJSON(state.featureCollection, {
      style: (feature) => styleBatalhao(feature, { visible: true }),
    }).addTo(state.map);

    rebuildLayerIndexFromGeoJsonLayer(legacyIndex);
  }

  function getLegacyMetadata(row) {
    return state.layerIndex[normalizeName(row?.municipio)]?.legacy || { html: "", fields: {} };
  }

  function getLegacyField(row, ...labels) {
    const fields = getLegacyMetadata(row).fields || {};
    for (const label of labels) {
      if (fields[label]) return fields[label];
    }
    return "";
  }

  function getObservationText(row) {
    return (
      row.justificativa_tecnica ||
      row.criterio_companhia ||
      row.criterio_decisao ||
      row.classificacao_analitica ||
      row.observacoes ||
      "Sem observação complementar."
    );
  }

  function getScenarioStructureCounts(rows) {
    const counts = { batalhao: 0, companhia: 0, pelotao: 0 };
    rows.forEach((row) => {
      counts[getTextureType(row)] += 1;
    });
    return counts;
  }

  function getFilteredStructureBattalions() {
    const battalions = sortBattalionStructures(state.raw.estrutura_final?.batalhoes || []);
    if (state.activeBatalhao === "Todos") return battalions;
    return battalions.filter((item) => item.batalhao === state.activeBatalhao);
  }

  function getFinalStructureCounts(respectFilter = true) {
    const battalions = respectFilter
      ? getFilteredStructureBattalions()
      : sortBattalionStructures(state.raw.estrutura_final?.batalhoes || []);
    if (!battalions.length) return null;
    return {
      batalhao: battalions.length,
      companhia: battalions.reduce((acc, item) => acc + (item.companhias?.length || 0), 0),
      pelotao: battalions.reduce(
        (acc, item) =>
          acc +
          (item.pelotoes_diretos_batalhao?.length || 0) +
          (item.companhias || []).reduce((companyAcc, cia) => companyAcc + (cia.pelotoes?.length || 0), 0),
        0,
      ),
    };
  }

  function buildStructureBreakdownHtml(rows, countsOverride = null) {
    const counts = countsOverride || getScenarioStructureCounts(rows);
    const total = counts.batalhao + counts.companhia + counts.pelotao || 1;
    const entries = [
      { key: "batalhao", label: "Batalhões", value: counts.batalhao },
      { key: "companhia", label: "Companhias", value: counts.companhia },
      { key: "pelotao", label: "Pelotões", value: counts.pelotao },
    ];
    return `
      <div class="proposal-breakdown">
        ${entries
          .map(
            (item) => `
              <div class="proposal-breakdown-row">
                <span class="proposal-breakdown-label">${item.label}</span>
                <div class="proposal-breakdown-track">
                  <span class="proposal-breakdown-fill proposal-breakdown-fill--${item.key}" style="width:${(
                    (item.value / total) *
                    100
                  ).toFixed(1)}%"></span>
                </div>
                <span class="proposal-breakdown-value">${item.value} · ${formatPercent((item.value / total) * 100)}</span>
              </div>
            `,
          )
          .join("")}
      </div>
    `;
  }

  function getLayerCenter(layer, fallbackRow) {
    if (layer) {
      if (typeof layer.getBounds === "function") {
        const bounds = layer.getBounds();
        if (bounds && typeof bounds.isValid === "function" && bounds.isValid()) {
          return bounds.getCenter();
        }
      }
      if (typeof layer.getLatLng === "function") {
        return layer.getLatLng();
      }
    }
    const lat = toNumber(fallbackRow?.latitude);
    const lng = toNumber(fallbackRow?.longitude);
    if (lat !== null && lng !== null) {
      return L.latLng(lat, lng);
    }
    return null;
  }

  function getSvgRoot() {
    return state.map?.getPanes?.().overlayPane?.querySelector("svg") || null;
  }

  function getPatternId(batalhao, texture) {
    return `cpraio-pattern-${normalizeName(batalhao).replace(/[^A-Z0-9]+/g, "-").toLowerCase()}-${texture}`;
  }

  function ensurePatternDefinition(batalhao, texture) {
    const svg = getSvgRoot();
    if (!svg) return null;
    let defs = svg.querySelector("defs[data-cpraio-patterns='true']");
    if (!defs) {
      defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
      defs.setAttribute("data-cpraio-patterns", "true");
      svg.prepend(defs);
    }

    const id = getPatternId(batalhao, texture);
    if (defs.querySelector(`#${id}`)) {
      return id;
    }

    const color = getBattalionColor(batalhao);
    const toneColor = getStructureToneColor(color, texture);
    const textureColor = getStructureAccentColor(color, texture);
    const pattern = document.createElementNS("http://www.w3.org/2000/svg", "pattern");
    pattern.setAttribute("id", id);
    pattern.setAttribute("patternUnits", "userSpaceOnUse");
    pattern.setAttribute("width", texture === "batalhao" ? "14" : "12");
    pattern.setAttribute("height", texture === "pelotao" ? "12" : "14");

    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    rect.setAttribute("width", "100%");
    rect.setAttribute("height", "100%");
    rect.setAttribute("fill", toneColor);
    rect.setAttribute("fill-opacity", texture === "batalhao" ? "0.98" : texture === "companhia" ? "0.94" : "0.9");
    pattern.appendChild(rect);

    if (texture === "companhia") {
      [
        ["-2", "12", "12", "-2"],
        ["2", "16", "16", "2"],
      ].forEach(([x1, y1, x2, y2]) => {
        const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
        line.setAttribute("x1", x1);
        line.setAttribute("y1", y1);
        line.setAttribute("x2", x2);
        line.setAttribute("y2", y2);
        line.setAttribute("stroke", textureColor);
        line.setAttribute("stroke-opacity", "0.65");
        line.setAttribute("stroke-width", "1.8");
        pattern.appendChild(line);
      });
    } else if (texture === "pelotao") {
      [
        ["3", "3"],
        ["9", "3"],
        ["3", "9"],
        ["9", "9"],
      ].forEach(([cx, cy]) => {
        const dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        dot.setAttribute("cx", cx);
        dot.setAttribute("cy", cy);
        dot.setAttribute("r", "1.5");
        dot.setAttribute("fill", textureColor);
        dot.setAttribute("fill-opacity", "0.72");
        pattern.appendChild(dot);
      });
    }

    defs.appendChild(pattern);
    return id;
  }

  function applyPatternToLayer(layer, row, visible) {
    if (!layer || !layer._path) return;
    const style = styleBatalhao(layer.feature, { visible });
    layer._path.setAttribute("fill", style.fillColor || (row ? getBattalionColor(getAssignedBatalhao(row)) : "#e5ebf0"));
    layer._path.setAttribute("fill-opacity", String(style.fillOpacity ?? (visible ? 0.5 : 0.08)));
  }

  function normalizeRegularRow(row) {
    return {
      municipio: row.municipio,
      latitude: row.latitude,
      longitude: row.longitude,
      populacao_ibge: row.populacao_ibge,
      populacao_ano_referencia: row.populacao_ano_referencia,
      status_atual: row.status_atual,
      status_sugerido_pre_hierarquia: row.status_sugerido_pre_hierarquia || row.status_atual,
      batalhao_atual: row.batalhao_atual,
      companhia_atual: row.companhia_atual,
      batalhao_cenario: row.batalhao_cenario,
      distancia_rodoviaria_ao_batalhao_atual_km: row.distancia_rodoviaria_ao_batalhao_atual_km,
      distancia_rodoviaria_ao_batalhao_cenario_km: row.distancia_rodoviaria_ao_batalhao_cenario_km,
      tempo_estimado_ao_batalhao_cenario_min: row.tempo_estimado_ao_batalhao_cenario_min,
      ganho_km: row.ganho_km,
      mudar_batalhao: parseBooleanFlag(row.mudar_batalhao),
      justificativa_tecnica: row.justificativa_tecnica,
      classificacao_analitica: row.classificacao_analitica,
      ganho_significativo: parseBooleanFlag(row.ganho_significativo),
      melhor_batalhao_disponivel: row.melhor_batalhao_disponivel,
      observacoes: row.observacoes,
      tipo_especial: row.tipo_especial || null,
      is_fortaleza: parseBooleanFlag(row.is_fortaleza),
    };
  }

  function normalizeFinalRow(row) {
    return {
      municipio: row.municipio,
      latitude: row.latitude,
      longitude: row.longitude,
      populacao_ibge: row.populacao_ibge,
      populacao_ano_referencia: row.populacao_ano_referencia,
      status_atual: row.status_atual,
      status_sugerido: row.status_sugerido,
      batalhao_atual: row.batalhao_atual,
      companhia_atual: row.companhia_atual,
      companhia_sugerida: row.companhia_sugerida,
      batalhao_sugerido: row.batalhao_sugerido,
      distancia_rodoviaria_ao_batalhao_atual_km: row.distancia_rodoviaria_ao_batalhao_atual_km,
      distancia_rodoviaria_ao_batalhao_sugerido_km: row.distancia_rodoviaria_ao_batalhao_sugerido_km,
      ganho_km: row.ganho_km,
      mudar_batalhao: parseBooleanFlag(row.mudar_batalhao),
      justificativa_tecnica: row.justificativa_tecnica,
      classificacao_analitica: row.classificacao_analitica,
      ganho_significativo: parseBooleanFlag(row.ganho_significativo),
      criterio_companhia: row.criterio_companhia,
      tipo_especial: row.tipo_especial || null,
      is_fortaleza: parseBooleanFlag(row.is_fortaleza),
    };
  }

  function makeScenarioModel(id, payload) {
    const rows = payload.municipios.map(normalizeRegularRow);
    return {
      id,
      title: payload.scenario.titulo,
      summary: payload.scenario,
      rows,
      battalions: payload.batalhoes || [],
      rowsByKey: Object.fromEntries(rows.map((row) => [normalizeName(row.municipio), row])),
    };
  }

  function makeFinalModel() {
    const comparison = state.raw.comparativo;
    const finalStructure = state.raw.estrutura_final;
    const recommendedId = state.recommendedScenarioId;
    const summary = comparison.cenarios[recommendedId];
    const rows = finalStructure.municipios.map(normalizeFinalRow);
    return {
      id: "final_recomendado",
      title: "Proposta Final Consolidada",
      summary: {
        ...summary,
        titulo: "Proposta Final Consolidada",
        descricao:
          "Estrutura operacional consolidada após roteamento rodoviário, restrição metropolitana Caucaia/Eusébio e reconstrução final das companhias.",
      },
      rows,
      battalions: finalStructure.batalhoes || [],
      rowsByKey: Object.fromEntries(rows.map((row) => [normalizeName(row.municipio), row])),
    };
  }

  function getActiveScenario() {
    return state.scenarios[state.activeScenarioId];
  }

  function isRowVisibleUnderCurrentFilter(row) {
    if (!row) return false;
    return state.activeBatalhao === "Todos" || getAssignedBatalhao(row) === state.activeBatalhao;
  }

  function getSelectedMunicipioRow() {
    const scenario = getActiveScenario();
    if (!scenario || !state.selectedMunicipioKey) return null;
    const row = scenario.rowsByKey[state.selectedMunicipioKey];
    if (!isRowVisibleUnderCurrentFilter(row)) return null;
    return row;
  }

  function getFilteredRows() {
    const scenario = getActiveScenario();
    if (!scenario) return [];
    if (state.activeBatalhao === "Todos") return scenario.rows;
    return scenario.rows.filter((row) => getAssignedBatalhao(row) === state.activeBatalhao);
  }

  function fitBoundsForRows(rows) {
    if (!state.map) return;
    if (state.activeBatalhao === "Todos" && state.geoJsonLayer) {
      const allBounds = state.geoJsonLayer.getBounds();
      if (allBounds && allBounds.isValid()) {
        state.map.fitBounds(allBounds.pad(0.015), {
          animate: true,
          duration: 0.6,
          maxZoom: 8,
        });
        return;
      }
    }
    const layers = rows
      .map((row) => state.layerIndex[normalizeName(row.municipio)]?.layer)
      .filter(Boolean);
    if (!layers.length) return;
    const bounds = L.featureGroup(layers).getBounds();
    if (!bounds || !bounds.isValid()) return;
    state.map.fitBounds(bounds.pad(state.activeBatalhao === "Todos" ? 0.035 : 0.08), {
      animate: true,
      duration: 0.6,
      maxZoom: state.activeBatalhao === "Todos" ? 8 : 10,
    });
  }

  function getBatalhoesForActiveScenario() {
    const scenario = getActiveScenario();
    if (!scenario) return [];
    if (state.activeScenarioId === "final_recomendado" && state.raw.estrutura_final?.batalhoes?.length) {
      return getFilteredStructureBattalions().map((item) => item.batalhao);
    }
    return sortBattalionNames(scenario.rows.map((row) => getAssignedBatalhao(row)));
  }

  function renderScenarioButtons() {
    const container = getById("mode-filters");
    if (!container) return;
    container.innerHTML = PROPOSAL_VIEW.map(
      (option) => `
        <button type="button" class="dashboard-filter-button is-active" aria-disabled="true" disabled>
          ${escapeHtml(option.label)}
        </button>
      `,
    ).join("");
  }

  function renderBatalhaoButtons() {
    const container = getById("batalhao-filters");
    if (!container) return;
    const batalhoes = ["Todos", ...getBatalhoesForActiveScenario()];
    container.innerHTML = batalhoes
      .map((nome) => {
        const active = nome === state.activeBatalhao;
        const color = nome === "Todos" ? "#163047" : getBattalionColor(nome);
        return `
          <button
            type="button"
            class="dashboard-filter-button dashboard-filter-button--batalhao ${active ? "is-active" : ""}"
            data-batalhao-id="${escapeHtml(nome)}"
            style="--batalhao-color:${escapeHtml(color)};"
          >
            ${escapeHtml(nome)}
          </button>
        `;
      })
      .join("");

    container.querySelectorAll("[data-batalhao-id]").forEach((button) => {
      button.addEventListener("click", () => {
        if (button.dataset.batalhaoId === "Todos") {
          state.activeBatalhao = "Todos";
          state.selectedMunicipioKey = null;
          render();
          fitBoundsForRows(getFilteredRows());
          return;
        }
        focusBatalhao(button.dataset.batalhaoId);
      });
    });
  }

  function renderScenarioCaption() {
    const el = getById("scenario-caption");
    if (!el) return;
    const scenario = getActiveScenario();
    const summary = scenario.summary;
    const rows = getFilteredRows();
    const stats = buildDistanceStats(rows);
    const recommended = state.raw.comparativo.recomendacao_final;
    const isFullScope = state.activeBatalhao === "Todos";
    const scopeLabel = isFullScope ? "Malha completa do estado" : `Recorte em ${state.activeBatalhao}`;
    const scopeTotalDistance =
      isFullScope ? summary.total_distance_km : rows.reduce((acc, row) => acc + (getTargetDistance(row) || 0), 0);
    const scopeGain =
      isFullScope ? summary.ganho_total_vs_atual_km : rows.reduce((acc, row) => acc + (getGain(row) || 0), 0);
    const scopeCentrality = isFullScope ? summary.centralidade_operacional_km : stats.avg;
    const scopeEfetivo = getRowsEfetivoTotal(rows);
    const scopeRedistributed = rows.filter((row) => isRedistributed(row)).length;
    const criticalShare = stats.count ? formatPercent((stats.critical / stats.count) * 100) : "0,0%";
    const battalionCount = new Set(rows.map((row) => getAssignedBatalhao(row))).size;
    const gainLabel = scopeGain >= 0 ? "Redução vs base atual" : "Aumento vs base atual";
    const recommendedMetro = recommended.batalhao_metropolitano_escolhido;
    const recommendationText = "Restrição administrativa aplicada: Caucaia e Eusébio atendem exclusivamente a Região Metropolitana.";
    const description = isFullScope
      ? `Proposta consolidada com ${recommendedMetro} como polo metropolitano complementar, mantendo a divisão exclusiva da RM entre Caucaia e Eusébio.`
      : `Recorte operacional de ${state.activeBatalhao} dentro da proposta final consolidada, com leitura específica do batalhão selecionado.`;
    const note = isFullScope
      ? recommendationText
      : `${scopeRedistributed} redistribuições no recorte, com centralidade média de ${formatKm(scopeCentrality)}.`;
    const cards = isFullScope
      ? [
          { value: formatKm(scopeTotalDistance), label: "Distância total da malha" },
          { value: formatKm(Math.abs(scopeGain)), label: gainLabel },
          { value: criticalShare, label: `Faixa crítica (${stats.critical} municípios)` },
          { value: formatInteger(scopeEfetivo), label: "Efetivo coberto" },
        ]
      : [
          { value: String(rows.length), label: "Municípios do recorte" },
          { value: formatKm(scopeTotalDistance), label: "Distância do recorte" },
          { value: formatInteger(scopeEfetivo), label: "Efetivo do recorte" },
          { value: criticalShare, label: `Faixa crítica (${stats.critical} municípios)` },
        ];
    const footerItems = isFullScope
      ? [
          scopeLabel,
          `${rows.length} municípios · ${battalionCount} batalhões`,
          `${scopeRedistributed} redistribuições`,
          `Centralidade ${formatKm(scopeCentrality)}`,
        ]
      : [
          scopeLabel,
          `${formatInteger(scopeEfetivo)} de efetivo`,
          `${scopeRedistributed} redistribuições`,
          `Maior distância ${formatKm(stats.max)}`,
        ];
    el.innerHTML = `
      <div class="scenario-summary-head">
        <div class="scenario-summary-kicker">Estrutura consolidada</div>
        <div class="scenario-summary-title-row">
          <strong>${escapeHtml(scenario.title)}</strong>
          <span class="scenario-summary-badge">Metropolitano: ${escapeHtml(recommendedMetro)}</span>
        </div>
        <div class="scenario-summary-description">${escapeHtml(description)}</div>
      </div>
      <div class="scenario-summary-stats">
        ${cards
          .map(
            (card) => `
              <div class="scenario-summary-stat">
                <strong>${escapeHtml(card.value)}</strong>
                <span>${escapeHtml(card.label)}</span>
              </div>
            `,
          )
          .join("")}
      </div>
      <div class="scenario-summary-footer">
        ${footerItems.map((item) => `<span class="scenario-summary-foot-item">${escapeHtml(item)}</span>`).join("")}
      </div>
      <div class="scenario-summary-note">${escapeHtml(note)}</div>
    `;
  }

  function renderKpis() {
    const scenario = getActiveScenario();
    if (!scenario) return;
    const rows = getFilteredRows();
    const structureCounts = state.activeScenarioId === "final_recomendado" ? getFinalStructureCounts() : null;
    const batalhoesAtivos = structureCounts?.batalhao ?? new Set(rows.map((row) => getAssignedBatalhao(row))).size;
    const companhiasAtivas =
      structureCounts?.companhia ?? rows.filter((row) => getTextureType(row) === "companhia").length;
    const efetivoTotal = getRowsEfetivoTotal(rows);
    const efetivoRealocado = getRowsEfetivoRealocado(rows);
    setText("kpi-municipios", String(rows.length));
    setText("kpi-batalhoes", String(batalhoesAtivos));
    setText("kpi-independentes", String(companhiasAtivas));
    setText("kpi-efetivo-geral", formatInteger(efetivoTotal));
    setText("kpi-realocado", formatInteger(efetivoRealocado));
    setText("kpi-municipios-label", "Municípios");
    setText("kpi-batalhoes-label", "Batalhões");
    setText("kpi-independentes-label", "Companhias");
    setText("kpi-efetivo-label", state.activeBatalhao === "Todos" ? "Efetivo Total" : "Efetivo do Recorte");
    setText("kpi-realocado-label", "Efetivo Redistribuído");
  }

  function renderScenarioCards() {
    const container = getById("efetivo-grid");
    if (!container) return;
    const comparison = state.raw.comparativo;
    const counts = state.activeScenarioId === "final_recomendado" ? getFinalStructureCounts(false) : null;
    container.innerHTML = PROPOSAL_VIEW.map((option) => {
      const scenario = state.scenarios[option.id];
      const summary = scenario.summary;
      const isActive = true;
      const isRecommended = true;
      const footerText = "Estrutura final consolidada com restrição metropolitana aplicada à dupla Caucaia/Eusébio.";
      const metro = summary.batalhao_metropolitano_escolhido || comparison.recomendacao_final.batalhao_metropolitano_escolhido;
      const tagLabel = "Final";
      const structureBreakdown = buildStructureBreakdownHtml(scenario.rows, counts);
      return `
        <article class="comparison-card ${isActive ? "is-active" : ""} ${isRecommended ? "is-recommended" : ""}" data-scenario-card="${option.id}">
          <div class="comparison-card-head">
            <h3>${escapeHtml(option.label)}</h3>
            <span class="comparison-card-tag">${escapeHtml(tagLabel)}</span>
          </div>
          <p class="comparison-card-lead">${escapeHtml(summary.descricao || scenario.title)}</p>
          <div class="comparison-metrics">
            <div class="comparison-metric"><small>Distância total</small><strong>${formatKm(summary.total_distance_km)}</strong></div>
            <div class="comparison-metric"><small>Centralidade</small><strong>${formatKm(summary.centralidade_operacional_km)}</strong></div>
            <div class="comparison-metric"><small>Mediana</small><strong>${formatKm(summary.median_distance_km)}</strong></div>
            <div class="comparison-metric"><small>P90</small><strong>${formatKm(summary.p90_distance_km)}</strong></div>
          </div>
          ${structureBreakdown}
          <div class="comparison-footer">
            <strong>${footerText}</strong><br />
            Redistribuídos: <strong>${summary.municipios_redistribuidos}</strong> ·
            Críticos: <strong>${summary.distancias_criticas}</strong> ·
            Ganho vs atual: <strong>${formatKm(summary.ganho_total_vs_atual_km || comparison.recomendacao_final.ganho_total_vs_atual_km || 0)}</strong>
          </div>
        </article>
      `;
    }).join("");
  }

  function buildDistanceStats(rows) {
    const distances = rows.map((row) => getTargetDistance(row)).filter((value) => value !== null);
    distances.sort((a, b) => a - b);
    const total = distances.reduce((acc, value) => acc + value, 0);
    const avg = distances.length ? total / distances.length : null;
    const median = distances.length
      ? distances.length % 2 === 1
        ? distances[(distances.length - 1) / 2]
        : (distances[distances.length / 2 - 1] + distances[distances.length / 2]) / 2
      : null;
    const p90Index = distances.length ? Math.max(0, Math.ceil(distances.length * 0.9) - 1) : 0;
    const p90 = distances.length ? distances[p90Index] : null;
    const min = distances.length ? distances[0] : null;
    const max = distances.length ? distances[distances.length - 1] : null;
    const near = distances.filter((value) => value <= 40).length;
    const mid = distances.filter((value) => value > 40 && value <= 80).length;
    const far = distances.filter((value) => value > 80 && value <= 150).length;
    const critical = distances.filter((value) => value > 150).length;
    return { total, avg, median, p90, min, max, near, mid, far, critical, count: distances.length };
  }

  function getOperationalReferenceLabel(row) {
    if (isIsolatedRow(row)) return "Unidade própria (sem subordinados)";
    const batalhao = getAssignedBatalhao(row);
    const texture = getTextureType(row);
    const companhia = row.companhia_sugerida || row.companhia_atual || "";
    if (texture === "batalhao") return `Sede de ${batalhao}`;
    if (companhia && normalizeName(companhia) !== normalizeName(row.municipio)) return companhia;
    return batalhao;
  }

  function buildHoverTooltipHtml(row, fallbackName = "Município do Ceará") {
    if (!row) {
      return `
        <div class="municipio-hover-card">
          <div class="municipio-hover-title">${escapeHtml(fallbackName)}</div>
          <div class="municipio-hover-line"><strong>Situação:</strong> fora da proposta operacional atual</div>
        </div>
      `;
    }
    if (isIsolatedRow(row)) {
      return `
        <div class="municipio-hover-card">
          <div class="municipio-hover-title">${escapeHtml(row.municipio)}</div>
          <div class="municipio-hover-line"><strong>Status:</strong> Batalhão isolado</div>
          <div class="municipio-hover-line"><strong>Efetivo:</strong> ${escapeHtml(formatInteger(getMunicipioEfetivo(row.municipio)))}</div>
          <div class="municipio-hover-line"><strong>Vinculação:</strong> não participa da redistribuição</div>
        </div>
      `;
    }
    const batalhao = getAssignedBatalhao(row);
    return `
      <div class="municipio-hover-card">
        <div class="municipio-hover-title">${escapeHtml(row.municipio)}</div>
        <div class="municipio-hover-line"><strong>Unidade:</strong> ${escapeHtml(formatStatusLabel(getSuggestedStatus(row)))}</div>
        <div class="municipio-hover-line"><strong>Batalhão:</strong> ${escapeHtml(batalhao)}</div>
        <div class="municipio-hover-line"><strong>Polo Operacional:</strong> ${escapeHtml(getOperationalReferenceLabel(row))}</div>
        <div class="municipio-hover-line"><strong>Distância rodoviária:</strong> ${formatKm(getTargetDistance(row))}</div>
      </div>
    `;
  }

  function buildInlineSparkBar(percent, modifier) {
    return `
      <span class="inline-spark">
        <span class="inline-spark-fill inline-spark-fill--${modifier}" style="width:${Math.max(0, Math.min(percent, 100)).toFixed(1)}%"></span>
      </span>
    `;
  }

  function buildStructureBadgeHtml(row) {
    const structureType = getTextureType(row);
    const label = formatStatusLabel(getSuggestedStatus(row));
    return `<span class="structure-badge structure-badge--${escapeHtml(structureType)}">${escapeHtml(label)}</span>`;
  }

  function buildDistanceTableRowHtml(row, selected = false) {
    const battalion = getAssignedBatalhao(row);
    const gain = getGain(row);
    const impactClass = gain && gain > 0 ? "impact-positive" : gain && gain < 0 ? "impact-negative" : "impact-neutral";
    const operationLabel = isIsolatedRow(row) ? "Isolado" : isRedistributed(row) ? "Redistribuído" : "Mantido";
    const companhiaLabel = row.companhia_sugerida || row.companhia_atual || "";
    const currentStatusLabel = formatStatusLabel(row.status_atual);
    const suggestedStatusLabel = formatStatusLabel(getSuggestedStatus(row));
    const changedStructure = normalizeName(currentStatusLabel) !== normalizeName(suggestedStatusLabel);
    return `
      <tr class="${selected ? "distance-row--selected" : ""}" data-municipio-key="${escapeHtml(normalizeName(row.municipio))}">
        <td>${escapeHtml(row.municipio)}</td>
        <td>
          <div class="table-structure-stack">
            <span class="batalhao-chip" style="background:${getBattalionColor(battalion)};">${escapeHtml(battalion)}</span>
            ${buildStructureBadgeHtml(row)}
          </div>
          ${changedStructure ? `<div class="table-subtle">Atual: ${escapeHtml(currentStatusLabel)}</div>` : ""}
          ${companhiaLabel ? `<div class="table-subtle">Polo interno: ${escapeHtml(companhiaLabel)}</div>` : ""}
        </td>
        <td>
          <strong>${formatKm(getTargetDistance(row))}</strong>
          <div class="table-subtle">Atual ${formatKm(getCurrentDistance(row))} · ${formatMinutes(row.tempo_estimado_ao_batalhao_cenario_min)}</div>
        </td>
        <td>
          <div class="${impactClass}">${operationLabel} · ${formatKm(gain)}</div>
          <div class="table-subtle">${escapeHtml(getObservationText(row))}</div>
        </td>
      </tr>
    `;
  }

  function renderScenarioStats() {
    const scenario = getActiveScenario();
    const rows = getFilteredRows();
    const selectedRow = getSelectedMunicipioRow();
    const scopedRows = selectedRow ? [selectedRow] : rows;
    const stats = buildDistanceStats(scopedRows);
    const context = getById("distance-context");
    const totalCities = getById("distance-total-cities");
    const metrics = getById("distance-metrics");
    const bars = getById("distance-bars");
    const list = getById("distance-list");
    const tableBody = getById("distance-full-body");

    if (!context || !totalCities || !metrics || !bars || !list || !tableBody) return;
    context.textContent = selectedRow
      ? `Foco Local · ${selectedRow.municipio}`
      : state.activeBatalhao === "Todos"
        ? scenario.title
        : `${scenario.title} · ${state.activeBatalhao}`;
    totalCities.textContent = selectedRow
      ? `${formatStatusLabel(getSuggestedStatus(selectedRow))} · ${getAssignedBatalhao(selectedRow)}`
      : `${rows.length} municípios`;

    const headers = document.querySelectorAll(".distance-full-table thead th");
    if (headers[1]) headers[1].textContent = "Batalhão / Estrutura";
    if (headers[3]) headers[3].textContent = "Observação técnica";

    if (selectedRow) {
      const currentDistance = getCurrentDistance(selectedRow);
      const targetDistance = getTargetDistance(selectedRow);
      const gain = getGain(selectedRow);
      const scaleMax = Math.max(currentDistance || 0, targetDistance || 0, Math.abs(gain || 0), 150);
      metrics.innerHTML = `
        <div class="distance-metric"><small>Distância atual</small><b>${formatKm(currentDistance)}</b></div>
        <div class="distance-metric"><small>Distância proposta</small><b>${formatKm(targetDistance)}</b></div>
        <div class="distance-metric"><small>Ganho logístico</small><b class="${gain && gain > 0 ? "impact-positive" : "impact-neutral"}">${formatKm(gain)}</b></div>
        <div class="distance-metric"><small>Tempo estimado</small><b>${formatMinutes(selectedRow.tempo_estimado_ao_batalhao_cenario_min)}</b></div>
        <div class="distance-metric"><small>Polo operacional</small><b>${escapeHtml(getOperationalReferenceLabel(selectedRow))}</b></div>
      `;

      bars.innerHTML = `
        <div class="distance-bar-row">
          <span class="bar-label">Atual</span>
          <div class="distance-bar-track"><span class="distance-bar-fill distance-fill-critical" style="width:${((currentDistance || 0) / scaleMax) * 100}%"></span></div>
          <span class="distance-bar-value">${formatKm(currentDistance)}</span>
        </div>
        <div class="distance-bar-row">
          <span class="bar-label">Proposta</span>
          <div class="distance-bar-track"><span class="distance-bar-fill distance-fill-near" style="width:${((targetDistance || 0) / scaleMax) * 100}%"></span></div>
          <span class="distance-bar-value">${formatKm(targetDistance)}</span>
        </div>
        <div class="distance-bar-row">
          <span class="bar-label">Ganho</span>
          <div class="distance-bar-track"><span class="distance-bar-fill distance-fill-mid" style="width:${(Math.abs(gain || 0) / scaleMax) * 100}%"></span></div>
          <span class="distance-bar-value">${formatKm(gain)}</span>
        </div>
      `;

      list.innerHTML = `
        <div class="selection-banner">
          <div class="selection-banner-copy">
            <strong>${escapeHtml(selectedRow.municipio)}</strong>
            <span>Painel sincronizado com o município selecionado no mapa.</span>
          </div>
          <button type="button" class="selection-banner-action" id="clear-municipio-selection">Limpar foco</button>
        </div>
        <div class="distance-list-item">
          <span>Batalhão sugerido</span>
          <b>${escapeHtml(getAssignedBatalhao(selectedRow))}</b>
        </div>
        <div class="distance-list-item">
          <span>Tipo de unidade</span>
          <b>${escapeHtml(formatStatusLabel(getSuggestedStatus(selectedRow)))}</b>
        </div>
        <div class="distance-list-item">
          <span>Polo operacional</span>
          <b>${escapeHtml(getOperationalReferenceLabel(selectedRow))}</b>
        </div>
        <div class="distance-list-item">
          <span>Classificação analítica</span>
          <b>${escapeHtml(selectedRow.classificacao_analitica || "n/d")}</b>
        </div>
        <div class="distance-list-item">
          <span>Justificativa técnica</span>
          <b>${escapeHtml(getObservationText(selectedRow))}</b>
        </div>
      `;

      getById("clear-municipio-selection")?.addEventListener("click", () => {
        clearSelectedMunicipio();
      });

      tableBody.innerHTML = buildDistanceTableRowHtml(selectedRow, true);
      tableBody.querySelectorAll("[data-municipio-key]").forEach((node) => {
        node.addEventListener("click", () => selectMunicipio(selectedRow));
      });
      return;
    }

    metrics.innerHTML = `
      <div class="distance-metric"><small>Distância total</small><b>${formatKm(stats.total)}</b></div>
      <div class="distance-metric"><small>Média</small><b>${formatKm(stats.avg)}</b></div>
      <div class="distance-metric"><small>Mediana</small><b>${formatKm(stats.median)}</b></div>
      <div class="distance-metric"><small>Mín · Máx</small><b>${formatKm(stats.min)} · ${formatKm(stats.max)}</b></div>
      <div class="distance-metric"><small>P90</small><b>${formatKm(stats.p90)}</b></div>
    `;

    const percentage = (value) => (stats.count ? ((value / stats.count) * 100).toFixed(1).replace(".", ",") : "0,0");
    const percentageNumber = (value) => (stats.count ? (value / stats.count) * 100 : 0);
    bars.innerHTML = `
      <div class="distance-bar-row">
        <span class="bar-label">Próxima</span>
        <div class="distance-bar-track"><span class="distance-bar-fill distance-fill-near" style="width:${percentage(stats.near)}%"></span></div>
        <span class="distance-bar-value">${stats.near} · ${percentage(stats.near)}%</span>
      </div>
      <div class="distance-bar-row">
        <span class="bar-label">Moderada</span>
        <div class="distance-bar-track"><span class="distance-bar-fill distance-fill-mid" style="width:${percentage(stats.mid)}%"></span></div>
        <span class="distance-bar-value">${stats.mid} · ${percentage(stats.mid)}%</span>
      </div>
      <div class="distance-bar-row">
        <span class="bar-label">Distante</span>
        <div class="distance-bar-track"><span class="distance-bar-fill distance-fill-far" style="width:${percentage(stats.far)}%"></span></div>
        <span class="distance-bar-value">${stats.far} · ${percentage(stats.far)}%</span>
      </div>
      <div class="distance-bar-row">
        <span class="bar-label">Crítica</span>
        <div class="distance-bar-track"><span class="distance-bar-fill distance-fill-critical" style="width:${percentage(stats.critical)}%"></span></div>
        <span class="distance-bar-value">${stats.critical} · ${percentage(stats.critical)}%</span>
      </div>
    `;

    const topGains = [...rows]
      .filter((row) => getGain(row) !== null)
      .sort((a, b) => (getGain(b) || 0) - (getGain(a) || 0))
      .slice(0, 5);
    const topCritical = [...rows]
      .sort((a, b) => (getTargetDistance(b) || 0) - (getTargetDistance(a) || 0))
      .slice(0, 5);
    const maintainedCount = rows.filter((row) => !row.mudar_batalhao).length;
    const significantCount = rows.filter((row) => row.ganho_significativo).length;
    const statusInfo =
      stats.critical >= 3 || percentageNumber(stats.critical) >= 10 || (stats.p90 || 0) > 170 || (stats.max || 0) > 300
        ? {
            cls: "distance-status-critical",
            title: "Situação Geral: Crítica",
            detail: "Concentração relevante de municípios acima de 150 km ou extremo logístico muito elevado.",
          }
        : stats.critical >= 1 || percentageNumber(stats.far + stats.critical) >= 25 || (stats.p90 || 0) > 120
          ? {
              cls: "distance-status-attention",
              title: "Situação Geral: Atenção",
              detail: "Há pressão logística em parte da malha e pontos que precisam de monitoramento.",
            }
          : percentageNumber(stats.mid) >= 50 || percentageNumber(stats.far + stats.critical) >= 15
            ? {
                cls: "distance-status-moderate",
                title: "Situação Geral: Moderada",
                detail: "Predomínio de cobertura moderada, com necessidade de gestão contínua.",
              }
            : {
                cls: "distance-status-stable",
                title: "Situação Geral: Estável",
                detail: "Predomínio de cobertura próxima/moderada e baixa pressão de longas distâncias.",
              };

    list.innerHTML = `
      <div class="distance-status-banner ${statusInfo.cls}">
        <strong>${statusInfo.title}</strong>
        <span>${statusInfo.detail}</span>
      </div>
      <div class="distance-list-title">Modelo Lista (Resumo)</div>
      <div class="distance-list-item">
        <span>Manutenção estrutural</span>
        <b>${maintainedCount} municípios · ${formatPercent(rows.length ? (maintainedCount / rows.length) * 100 : 0)}</b>
      </div>
      <div class="distance-list-item">
        <span>Ganhos significativos</span>
        <b>${significantCount} municípios</b>
      </div>
      <div class="distance-list-item">
        <span>Próxima (&lt;40 km)</span>
        <div class="distance-list-item-tail">
          ${buildInlineSparkBar(percentageNumber(stats.near), "near")}
          <b>${stats.near} municípios (${percentage(stats.near)}%)</b>
        </div>
      </div>
      <div class="distance-list-item">
        <span>Moderada (40-80 km)</span>
        <div class="distance-list-item-tail">
          ${buildInlineSparkBar(percentageNumber(stats.mid), "mid")}
          <b>${stats.mid} municípios (${percentage(stats.mid)}%)</b>
        </div>
      </div>
      <div class="distance-list-item">
        <span>Distante (80,1-150 km)</span>
        <div class="distance-list-item-tail">
          ${buildInlineSparkBar(percentageNumber(stats.far), "far")}
          <b>${stats.far} municípios (${percentage(stats.far)}%)</b>
        </div>
      </div>
      <div class="distance-list-item">
        <span>Crítica (&gt;150 km)</span>
        <div class="distance-list-item-tail">
          ${buildInlineSparkBar(percentageNumber(stats.critical), "critical")}
          <b>${stats.critical} municípios (${percentage(stats.critical)}%)</b>
        </div>
      </div>
      <div class="distance-list-title">Maiores ganhos logísticos</div>
      ${topGains
        .map(
          (row) => `
            <div class="distance-list-item">
              <span>${escapeHtml(row.municipio)}</span>
              <b class="${(getGain(row) || 0) > 0 ? "impact-positive" : "impact-neutral"}">${formatKm(getGain(row))}</b>
            </div>
          `,
        )
        .join("")}
      <div class="distance-ranking">
        <div class="distance-list-title">Maiores distâncias do recorte</div>
        ${topCritical
          .map(
            (row) => `
              <div class="distance-list-item">
                <span>${escapeHtml(row.municipio)}</span>
                <b>${formatKm(getTargetDistance(row))}</b>
              </div>
            `,
          )
          .join("")}
      </div>
    `;

    tableBody.innerHTML = [...rows]
      .sort((a, b) => (getTargetDistance(b) || 0) - (getTargetDistance(a) || 0))
      .map((row) => buildDistanceTableRowHtml(row, false))
      .join("");

    tableBody.querySelectorAll("[data-municipio-key]").forEach((node) => {
      node.addEventListener("click", () => {
        const row = scenario.rowsByKey[node.dataset.municipioKey];
        if (row) selectMunicipio(row);
      });
    });
  }

  function renderHierarchy() {
    const container = getById("city-structure-view");
    if (!container) return;
    const scenario = getActiveScenario();
    if (!scenario) return;

    if (state.activeScenarioId === "final_recomendado") {
      const battalions = sortBattalionStructures(state.raw.estrutura_final.batalhoes).filter(
        (item) => state.activeBatalhao === "Todos" || item.batalhao === state.activeBatalhao,
      );
      container.innerHTML = battalions
        .map(
          (item) => {
            const batalhaoRows = scenario.rows.filter((row) => getAssignedBatalhao(row) === item.batalhao);
            const efetivoTotal = getRowsEfetivoTotal(batalhaoRows);
            const pelotoesIndiretos = item.companhias.reduce((acc, cia) => acc + cia.pelotoes.length, 0);
            return `
            <article class="hierarchy-card hierarchy-card--interactive" data-focus-batalhao="${escapeHtml(item.batalhao)}" style="--accent-color:${escapeHtml(getBattalionColor(item.batalhao))};">
              <div class="hierarchy-head">
                <div>
                  <h3>${escapeHtml(item.batalhao)}</h3>
                  <div class="hierarchy-meta">${item.municipios_total} municípios · ${item.redistribuidos_recebidos} recebidos · ${formatInteger(efetivoTotal)} de efetivo</div>
                </div>
                <span class="hierarchy-pill" style="background:${escapeHtml(rgba(getBattalionColor(item.batalhao), 0.14))}; color:${escapeHtml(getBattalionColor(item.batalhao))};">${escapeHtml(item.municipio_sede)}</span>
              </div>
              <div class="hierarchy-stats">
                <span class="hierarchy-stat">1 sede</span>
                <span class="hierarchy-stat">${item.companhias.length} companhias</span>
                <span class="hierarchy-stat">${pelotoesIndiretos} pelotões por companhia</span>
                <span class="hierarchy-stat">${item.pelotoes_diretos_batalhao.length} pelotões diretos</span>
                <span class="hierarchy-stat hierarchy-stat--accent">${formatInteger(efetivoTotal)} de efetivo</span>
              </div>
              ${item.companhias.length
                ? `
                  <div class="hierarchy-block">
                    <div class="hierarchy-block-title">Companhias</div>
                    ${item.companhias
                      .map(
                        (cia) => `
                          <div class="hierarchy-line">
                            <span><strong>${escapeHtml(cia.companhia)}</strong> · ${escapeHtml(cia.origem_sugestao)}</span>
                            <span>${cia.pelotoes.length} pelotões</span>
                          </div>
                          ${cia.pelotoes
                            .map(
                              (pel) => `
                                <div class="hierarchy-line">
                                  <span>${escapeHtml(pel)}</span>
                                  <span>Pelotão</span>
                                </div>
                              `,
                            )
                            .join("")}
                        `,
                      )
                      .join("")}
                  </div>
                `
                : ""}
              ${item.pelotoes_diretos_batalhao.length
                ? `
                  <div class="hierarchy-block">
                    <div class="hierarchy-block-title">Pelotões diretos da sede</div>
                    ${item.pelotoes_diretos_batalhao
                      .map(
                        (pel) => `
                          <div class="hierarchy-line">
                            <span>${escapeHtml(pel)}</span>
                            <span>Subordinado à sede</span>
                          </div>
                        `,
                      )
                      .join("")}
                  </div>
                `
                : ""}
            </article>
          `;
          },
        )
        .join("");
      container.querySelectorAll("[data-focus-batalhao]").forEach((node) => {
        node.addEventListener("click", () => focusBatalhao(node.dataset.focusBatalhao));
      });
      return;
    }

    const grouped = {};
    getFilteredRows().forEach((row) => {
      const batalhao = getAssignedBatalhao(row);
      grouped[batalhao] = grouped[batalhao] || [];
      grouped[batalhao].push(row);
    });

    container.innerHTML = Object.entries(grouped)
      .sort(([a], [b]) => compareBattalionNames(a, b))
      .map(([batalhao, rows]) => {
        const changed = rows.filter((row) => isRedistributed(row)).length;
        const structure = getScenarioStructureCounts(rows);
        const efetivoTotal = getRowsEfetivoTotal(rows);
        const top = [...rows]
          .sort((a, b) => (getGain(b) || 0) - (getGain(a) || 0))
          .slice(0, 6);
        return `
          <article class="hierarchy-card hierarchy-card--interactive" data-focus-batalhao="${escapeHtml(batalhao)}" style="--accent-color:${escapeHtml(getBattalionColor(batalhao))};">
            <div class="hierarchy-head">
              <div>
                <h3>${escapeHtml(batalhao)}</h3>
                <div class="hierarchy-meta">${rows.length} municípios · ${changed} redistribuídos · ${formatInteger(efetivoTotal)} de efetivo</div>
              </div>
              <span class="hierarchy-pill">Pré-hierarquia</span>
            </div>
            <div class="hierarchy-stats">
              <span class="hierarchy-stat">${structure.batalhao} sedes</span>
              <span class="hierarchy-stat">${structure.companhia} companhias</span>
              <span class="hierarchy-stat">${structure.pelotao} pelotões</span>
              <span class="hierarchy-stat hierarchy-stat--accent">${formatInteger(efetivoTotal)} de efetivo</span>
            </div>
            <div class="insight-list">
              ${top
                .map(
                  (row) => `
                    <div class="insight-item">
                      <span>${escapeHtml(row.municipio)}</span>
                      <strong class="${(getGain(row) || 0) > 0 ? "impact-positive" : "impact-neutral"}">${formatKm(getGain(row))}</strong>
                    </div>
                  `,
                )
                .join("")}
            </div>
          </article>
        `;
      })
      .join("");

    container.querySelectorAll("[data-focus-batalhao]").forEach((node) => {
      node.addEventListener("click", () => focusBatalhao(node.dataset.focusBatalhao));
    });
  }

  function renderExecutiveSummary() {
    const target = getById("executive-text");
    if (!target) return;
    const report = state.raw.relatorio;
    const recommendation = report.recomendacao_final;
    const totals = report.totais;
    const active = getActiveScenario();
    const selectedRow = getSelectedMunicipioRow();
    const top = report.ranking_maiores_ganhos.slice(0, 5).map((row) => row.municipio).join(", ");
    const sensitive = report.ranking_casos_sensiveis
      .slice(0, 5)
      .map((row) => `${row.municipio} (${formatKm(getTargetDistance(row))})`)
      .join(", ");
    target.innerHTML = `
      ${
        selectedRow
          ? `
            <div class="summary-highlight">
              <strong>Foco local:</strong> ${escapeHtml(selectedRow.municipio)} · ${escapeHtml(formatStatusLabel(getSuggestedStatus(selectedRow)))} · ${formatKm(getTargetDistance(selectedRow))} até o polo operacional.
            </div>
          `
          : ""
      }
      <div class="summary-highlight">
        <strong>Definição metropolitana:</strong> ${escapeHtml(recommendation.batalhao_metropolitano_escolhido)} como batalhão complementar da RM, ao lado de Caucaia.
      </div>
      <div class="summary-line">
        <strong>Critério principal</strong>
        <span>A proposta final consolidada trabalha apenas com Eusébio como nova alternativa metropolitana, mantendo Caucaia e Eusébio restritos à Região Metropolitana.</span>
      </div>
      <div class="summary-line">
        <strong>Critério complementar</strong>
        <span>O roteamento considera distância rodoviária real e impede que municípios fora da Região Metropolitana sejam alocados em Caucaia ou Eusébio.</span>
      </div>
      <div class="summary-line">
        <strong>Ganho agregado</strong>
        <span>${formatKm(recommendation.ganho_total_vs_atual_km)} de redução logística sobre a base atual, equivalente a ${formatPercent(recommendation.ganho_percentual_vs_atual)}.</span>
      </div>
      <div class="summary-line">
        <strong>Proposta em foco</strong>
        <span>${escapeHtml(active.title)} com ${active.summary.municipios_redistribuidos} redistribuições, ${active.summary.distancias_criticas} casos críticos e ${formatPercent(active.summary.percentual_manutencao_estrutura)} de manutenção estrutural.</span>
      </div>
      <div class="summary-line">
        <strong>Municípios de maior ganho</strong>
        <span>${escapeHtml(top || "n/d")}.</span>
      </div>
      <div class="summary-line">
        <strong>Casos sensíveis</strong>
        <span>${escapeHtml(sensitive || "n/d")}.</span>
      </div>
    `;
  }

  function buildPopupHtml(row, fallbackName = "Município do Ceará") {
    if (!row) {
      return `
        <div class="popup-shell">
          <div class="popup-head">
            <div class="popup-title">${escapeHtml(fallbackName)}</div>
          </div>
          <div class="popup-note">Município exibido na malha estadual, sem vinculação na proposta operacional carregada.</div>
        </div>
      `;
    }
    if (isIsolatedRow(row)) {
      const efetivo = getMunicipioEfetivo(row.municipio);
      return `
        <div class="popup-shell">
          <div class="popup-head">
            <div class="popup-title">${escapeHtml(row.municipio)}</div>
            <span class="popup-badge" style="background:${escapeHtml(rgba(getBattalionColor(row.municipio), 0.14))}; color:${escapeHtml(getBattalionColor(row.municipio))};">Batalhão isolado</span>
          </div>
          <div class="popup-note">Fortaleza não vincula outros municípios e foi removida da disputa de redistribuição territorial.</div>
          <div class="popup-section-title">Dados operacionais</div>
          <div class="popup-grid">
            <div class="popup-item"><small>Município</small><strong>${escapeHtml(row.municipio)}</strong></div>
            <div class="popup-item"><small>Efetivo</small><strong>${escapeHtml(formatInteger(efetivo))}</strong></div>
            <div class="popup-item"><small>Status</small><strong>Batalhão isolado</strong></div>
            <div class="popup-item"><small>Observação</small><strong>Não vincula outros municípios</strong></div>
          </div>
        </div>
      `;
    }
    const battalion = getAssignedBatalhao(row);
    const status = getSuggestedStatus(row);
    const gain = getGain(row);
    const gainClass = gain && gain > 0 ? "impact-positive" : gain && gain < 0 ? "impact-negative" : "impact-neutral";
    const officialPopulation = toNumber(row.populacao_ibge);
    const population = officialPopulation === null ? getLegacyField(row, "População") : null;
    const idh = getLegacyField(row, "IDH");
    const pib = getLegacyField(row, "PIB per capita");
    const density = getLegacyField(row, "Densidade");
    const legacyDistance = getLegacyField(row, "Distância à sede", "Distancia à sede");
    const legacyJustification = getLegacyField(row, "Justificativa");
    const movementLabel = row.mudar_batalhao ? "Redistribuído" : "Mantido";
    const contextItems = [
      { label: "População", value: population },
      { label: "IDH", value: idh },
      { label: "PIB per capita", value: pib },
      { label: "Densidade", value: density },
      { label: "Distância histórica", value: legacyDistance },
    ].filter((item) => item.value);
    return `
      <div class="popup-shell">
        <div class="popup-head">
          <div class="popup-title">${escapeHtml(row.municipio)}</div>
          <span class="popup-badge" style="background:${escapeHtml(rgba(getBattalionColor(battalion), 0.14))}; color:${escapeHtml(getBattalionColor(battalion))};">${escapeHtml(battalion)}</span>
        </div>
        <div class="popup-note">${escapeHtml(getObservationText(row))}</div>
        <div class="popup-section-title">Proposta operacional</div>
        <div class="popup-grid">
          ${
            officialPopulation !== null
              ? `<div class="popup-item"><small>População IBGE ${escapeHtml(row.populacao_ano_referencia || "atual")}</small><strong>${escapeHtml(formatInteger(officialPopulation))}</strong></div>`
              : ""
          }
          <div class="popup-item"><small>Efetivo</small><strong>${escapeHtml(formatInteger(getMunicipioEfetivo(row.municipio)))}</strong></div>
          <div class="popup-item"><small>Movimento</small><strong>${escapeHtml(movementLabel)}</strong></div>
          <div class="popup-item"><small>Ganho logístico</small><strong class="${gainClass}">${formatKm(gain)}</strong></div>
          <div class="popup-item"><small>Batalhão atual</small><strong>${escapeHtml(row.batalhao_atual || "—")}</strong></div>
          <div class="popup-item"><small>Batalhão sugerido</small><strong>${escapeHtml(battalion)}</strong></div>
          <div class="popup-item"><small>Status atual</small><strong>${escapeHtml(formatStatusLabel(row.status_atual))}</strong></div>
          <div class="popup-item"><small>Status sugerido</small><strong>${escapeHtml(formatStatusLabel(status))}</strong></div>
          <div class="popup-item"><small>Distância atual</small><strong>${formatKm(getCurrentDistance(row))}</strong></div>
          <div class="popup-item"><small>Distância sugerida</small><strong>${formatKm(getTargetDistance(row))}</strong></div>
          <div class="popup-item"><small>Tempo estimado</small><strong>${formatMinutes(row.tempo_estimado_ao_batalhao_cenario_min)}</strong></div>
          <div class="popup-item"><small>Polo interno</small><strong>${escapeHtml(row.companhia_sugerida || row.companhia_atual || "Sede")}</strong></div>
        </div>
        ${
          contextItems.length
            ? `
              <div class="popup-section-title">Dados de referência</div>
              <div class="popup-grid popup-grid--context">
                ${contextItems
                  .map(
                    (item) => `
                      <div class="popup-item">
                        <small>${escapeHtml(item.label)}</small>
                        <strong>${escapeHtml(item.value)}</strong>
                      </div>
                    `,
                  )
                  .join("")}
              </div>
            `
            : ""
        }
        ${
          legacyJustification
            ? `<div class="popup-note"><strong>Perfil do município:</strong> ${escapeHtml(legacyJustification)}</div>`
            : ""
        }
      </div>
    `;
  }

  function getStyleForRow(row, visible) {
    const batalhao = getAssignedBatalhao(row);
    const statusTexture = getTextureType(row);
    const baseColor = getBattalionColor(batalhao);
    const fillColor = getStructureToneColor(baseColor, statusTexture);
    const isSeat = statusTexture === "batalhao";
    const changed = Boolean(row.mudar_batalhao);
    const significant = Boolean(row.ganho_significativo);
    const borderColor = getStructureAccentColor(baseColor, statusTexture);
    return {
      color: !visible ? "#d4dee6" : significant && !isSeat ? blendColor(borderColor, -0.14) : borderColor,
      weight: !visible ? 1 : isSeat ? 4.8 : statusTexture === "companhia" ? 2.9 : 2.1,
      opacity: !visible ? 0.18 : 0.98,
      fillColor,
      fillOpacity: !visible ? 0.08 : 1,
      dashArray: !visible ? null : statusTexture === "companhia" ? "10 4" : statusTexture === "pelotao" ? "3 6" : null,
      className: changed ? "municipio-redistribuido" : "",
    };
  }

  function renderMap() {
    // O front só troca estilo, popup e linhas operacionais; a base cartográfica original é preservada.
    const active = getActiveScenario();
    if (!active) return;
    const filteredRows = getFilteredRows();
    const visibleKeys = new Set(filteredRows.map((row) => normalizeName(row.municipio)));
    const allRowsByKey = active.rowsByKey;

    Object.values(state.layerIndex).forEach((entry) => {
      const row = allRowsByKey[entry.key];
      if (typeof entry.layer.setStyle !== "function") return;
      const visible = row ? visibleKeys.has(entry.key) : true;
      entry.layer.setStyle(styleBatalhao(entry.layer.feature, { visible }));
      if (row) {
        applyPatternToLayer(entry.layer, row, visible);
      }
      if (entry.layer._path) {
        entry.layer._path.classList.toggle("municipio-redistribuido", visible && Boolean(row?.mudar_batalhao));
        entry.layer._path.classList.toggle("municipio-batalhao", visible && row ? getTextureType(row) === "batalhao" : false);
        entry.layer._path.classList.toggle("municipio-selecionado", visible && state.selectedMunicipioKey === entry.key);
      }
      if (visible && row && getTextureType(row) === "batalhao" && typeof entry.layer.bringToFront === "function") {
        entry.layer.bringToFront();
      }
      entry.layer.bindPopup(buildPopupHtml(row, entry.name), { maxWidth: 360 });
      if (typeof entry.layer.bindTooltip === "function") {
        if (typeof entry.layer.unbindTooltip === "function") {
          entry.layer.unbindTooltip();
        }
        entry.layer.bindTooltip(buildHoverTooltipHtml(row, entry.name), {
          direction: "top",
          sticky: true,
          opacity: 0.98,
          className: "municipio-hover-tooltip",
        });
      }
      if (!entry.clickBound && typeof entry.layer.on === "function") {
        entry.layer.on("click", () => {
          const currentScenario = getActiveScenario();
          const currentRow = currentScenario?.rowsByKey?.[entry.key];
          if (!currentRow) return;
          selectMunicipio(currentRow);
        });
        entry.layer.on("mouseout", () => {
          const currentScenario = getActiveScenario();
          const currentRow = currentScenario?.rowsByKey?.[entry.key];
          const stillVisible = currentRow ? state.activeBatalhao === "Todos" || getAssignedBatalhao(currentRow) === state.activeBatalhao : true;
          entry.layer.setStyle(styleBatalhao(entry.layer.feature, { visible: stillVisible }));
          if (currentRow) {
            applyPatternToLayer(entry.layer, currentRow, stillVisible);
          }
        });
        entry.layer.on("mouseover", () => {
          const currentScenario = getActiveScenario();
          const currentRow = currentScenario?.rowsByKey?.[entry.key];
          const stillVisible = currentRow ? state.activeBatalhao === "Todos" || getAssignedBatalhao(currentRow) === state.activeBatalhao : true;
          const baseStyle = styleBatalhao(entry.layer.feature, { visible: stillVisible });
          entry.layer.setStyle({
            ...baseStyle,
            weight: (baseStyle.weight || 2) + 0.9,
            color: blendColor(baseStyle.color || (currentRow ? getBattalionColor(getAssignedBatalhao(currentRow)) : "#64748b"), -0.18),
          });
        });
        entry.clickBound = true;
      }
    });

    state.lineLayer.clearLayers();
    state.markerLayer.clearLayers();

    const battalions = state.activeBatalhao === "Todos" ? getBatalhoesForActiveScenario() : [state.activeBatalhao];
    battalions.forEach((batalhao) => {
      const seatRow = active.rows.find((row) => row.municipio === batalhao) || { municipio: batalhao };
      const seatEntry = state.layerIndex[normalizeName(batalhao)];
      const seatCenter = getLayerCenter(seatEntry?.layer, seatRow);
      if (!seatCenter) return;
      const isIsolatedSeat = isFortalezaName(batalhao);
      L.circleMarker(seatCenter, {
        radius: isIsolatedSeat ? 18 : 15,
        color: rgba("#ffffff", 0.9),
        weight: isIsolatedSeat ? 2.8 : 2,
        fillColor: getBattalionColor(batalhao),
        fillOpacity: isIsolatedSeat ? 0.3 : 0.22,
      }).addTo(state.markerLayer);
      L.circleMarker(seatCenter, {
        radius: isIsolatedSeat ? 11.5 : 10,
        color: "#ffffff",
        weight: isIsolatedSeat ? 3.6 : 2.8,
        fillColor: getBattalionColor(batalhao),
        fillOpacity: 1,
      })
        .bindTooltip(isIsolatedSeat ? `Batalhão isolado: ${batalhao}` : `Sede de batalhão: ${batalhao}`, { direction: "top" })
        .on("click", () => focusBatalhao(batalhao))
        .addTo(state.markerLayer);
      if (isIsolatedSeat && !state.fortalezaMarkerLogged) {
        console.info("Fortaleza exibida como batalhão isolado");
        state.fortalezaMarkerLogged = true;
      }
    });

    filteredRows.forEach((row) => {
      const battalion = getAssignedBatalhao(row);
      if (row.municipio === battalion) return;
      const fromEntry = state.layerIndex[normalizeName(row.municipio)];
      const toEntry = state.layerIndex[normalizeName(battalion)];
      const from = getLayerCenter(fromEntry?.layer, row);
      const to = getLayerCenter(toEntry?.layer, active.rows.find((item) => item.municipio === battalion));
      if (!from || !to) return;
      L.polyline([from, to], {
        color: getBattalionColor(battalion),
        weight: row.ganho_significativo ? 3 : 1.8,
        opacity: 0.64,
        dashArray: row.ganho_significativo ? "9 5" : "5 5",
      }).addTo(state.lineLayer);
    });
  }

  function showLoadError(error) {
    const hint =
      window.location.protocol === "file:"
        ? "Abra o painel por HTTP local, por exemplo com `python3 -m http.server 8000`, para permitir o carregamento dos JSON em /output."
        : "Verifique se os arquivos em /output foram gerados e se o dashboard está sendo servido por HTTP.";
    const message = `${error.message || error}. ${hint}`;
    const html = `<div class="dashboard-load-error">${escapeHtml(message)}</div>`;
    ["efetivo-grid", "city-structure-view", "executive-text", "distance-list"].forEach((id) => {
      const node = getById(id);
      if (node) node.innerHTML = html;
    });
    setText("scenario-caption", "Falha ao carregar a proposta operacional consolidada.");
    console.error("Falha no dashboard dinâmico:", error);
  }

  async function loadAllData() {
    const [municipiosGeoJson, efetivoPorMunicipio, comparativo, estruturaFinal, relatorio] = await Promise.all([
      fetchJson(MUNICIPAL_GEOJSON_FILE),
      loadEfetivoData(),
      fetchJson(OUTPUT_FILES.comparativo),
      fetchJson(OUTPUT_FILES.estrutura_final),
      fetchJson(OUTPUT_FILES.relatorio),
    ]);

    const sortedEstruturaFinal = {
      ...estruturaFinal,
      batalhoes: sortBattalionStructures(estruturaFinal.batalhoes || []),
    };

    state.raw = {
      municipios_geojson: municipiosGeoJson,
      efetivo_por_municipio: efetivoPorMunicipio,
      comparativo,
      estrutura_final: sortedEstruturaFinal,
      relatorio,
    };
    state.municipiosGeoJson = municipiosGeoJson;
    state.efetivoByMunicipio = efetivoPorMunicipio;
    state.recommendedScenarioId = comparativo.recomendacao_final.scenario_id;
    state.scenarios = {
      final_recomendado: makeFinalModel(),
    };
    logFortalezaValidation();
  }

  async function loadEfetivoData() {
    try {
      return parseEfetivoJson(await fetchJson(EFETIVO_JSON_FILE));
    } catch (error) {
      console.warn("Falha ao carregar o JSON atualizado de efetivo; tentando fallback legado.", error);
      try {
        return parseEfetivoMarkdown(await fetchText(LEGACY_EFETIVO_MARKDOWN_FILE));
      } catch (legacyError) {
        console.error("Falha ao carregar os dados de efetivo; seguindo com efetivo zerado no dashboard.", legacyError);
        return {};
      }
    }
  }

  function logFortalezaValidation() {
    if (state.fortalezaValidationLogged) return;
    const finalScenario = state.scenarios.final_recomendado;
    const fortalezaRow = finalScenario?.rowsByKey?.[FORTALEZA_KEY];
    const fortalezaEfetivo = state.efetivoByMunicipio[FORTALEZA_KEY];

    if (!fortalezaRow) {
      console.warn("Fortaleza não foi encontrada na proposta carregada.");
      return;
    }

    console.info("Fortaleza carregada com sucesso", {
      municipio: fortalezaRow.municipio,
      efetivo: fortalezaEfetivo ?? 0,
      tipo: fortalezaRow.tipo_especial || "BATALHAO_ISOLADO",
    });

    const recebeMunicipios = finalScenario.rows.some(
      (row) => !isFortalezaName(row.municipio) && getAssignedBatalhao(row) === fortalezaRow.municipio,
    );
    if (!recebeMunicipios) {
      console.info("Fortaleza removida da lista de polos de redistribuição");
    }

    state.fortalezaValidationLogged = true;
  }

  function render() {
    renderSidePanelShell();
    renderScenarioButtons();
    renderBatalhaoButtons();
    renderScenarioCaption();
    renderKpis();
    renderScenarioCards();
    renderScenarioStats();
    renderHierarchy();
    renderExecutiveSummary();
    renderMap();
  }

  async function init({ map, batalhaoLayers }) {
    if (state.initialized || state.loading) return;
    state.loading = true;
    state.map = map;
    state.batalhaoLayers = batalhaoLayers;
    state.lineLayer = L.layerGroup().addTo(map);
    state.markerLayer = L.layerGroup().addTo(map);
    syncResponsiveState();
    bindSidePanelControls();
    bindViewportResize();

    try {
      await loadAllData();
      buildLayerIndex();
      state.initialized = true;
      state.activeScenarioId = "final_recomendado";
      state.activeBatalhao = "Todos";
      render();
      setTimeout(() => {
        state.map.invalidateSize();
        fitBoundsForRows(getFilteredRows());
      }, 150);
    } catch (error) {
      showLoadError(error);
    } finally {
      state.loading = false;
    }
  }

  return { init };
})();
