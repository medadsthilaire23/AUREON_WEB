// shared/static/admin/js/ops.js
// ══════════════════════════════════════════════════════════════════════════════
// Mapa de operaciones — AUREON v4.0
//
// Fuente de verdad: management/data/tabla_operacion.json
// Sincronizado con event_id.py (GATE_ALIASES) y event_state.py (STATE_COLORS)
//
// Cambios v4.0:
//   - Gates nuevos: S (SecurityGate), LG (LoginGate), AG (AccessGate), VG (VerificacionGate)
//   - Módulos nuevos: frontend, discovery
//   - Ops nuevas: OP011–OP039 (auth pages, account, sessions)
//   - Prefijos de anomalía: XX, AD, UR, FL, GB, FA, TM, SA
// ══════════════════════════════════════════════════════════════════════════════

// ── Aliases de gates — espejo de event_id.py GATE_ALIASES ────────────────────
const GATE_ALIASES = {
  // Nivel 1 — Infraestructura
  "HttpGate":         "H",
  "DbGate":           "D",
  "ModuleGate":       "M",
  "BootGate":         "B",
  // Nivel 2 — Sub-Gates de Dominio (v4.0)
  "LoginGate":        "LG",
  "AccessGate":       "AG",
  "VerificacionGate": "VG",
  // Nivel 3 — Gates Especiales (v4.0)
  "SecurityGate":     "S",
  // Feature flags
  "oauth_google":     "OG",
  "oauth_github":     "OGH",
  "passkey_login":    "PL",
  "registration":     "R",
};

// Índice inverso: alias → nombre completo
const ALIAS_TO_GATE = Object.fromEntries(
  Object.entries(GATE_ALIASES).map(([k, v]) => [v, k])
);

const GATE_FULL = {
  H:   "HttpGate",
  D:   "DbGate",
  M:   "ModuleGate",
  B:   "BootGate",
  S:   "SecurityGate",
  LG:  "LoginGate",
  AG:  "AccessGate",
  VG:  "VerificacionGate",
  OG:  "oauth_google",
  OGH: "oauth_github",
  PL:  "passkey_login",
  R:   "registration",
};

// ── Prefijos de anomalía — espejo de event_state.py ANOMALY_PREFIXES ─────────
const ANOMALY_PREFIXES = new Set(["XX","AD","UR","FL","GB","FA","TM","SA"]);

const ANOMALY_META = {
  XX: { label:"Discovery",      level:"ROJA_CRITICA", color:"red"    },
  AD: { label:"Admin",          level:"ROJA",         color:"red"    },
  FL: { label:"Falso Loc",      level:"ROJA",         color:"red"    },
  GB: { label:"Gate Bloqueado", level:"ROJA",         color:"red"    },
  SA: { label:"Saturación",     level:"ROJA",         color:"red"    },
  FA: { label:"Fallo Técnico",  level:"NARANJA",      color:"orange" },
  TM: { label:"Timeout",        level:"NARANJA",      color:"orange" },
  UR: { label:"Usuario",        level:"AMARILLA",     color:"yellow" },
};

function isAnomalyOp(opId) {
  if (!opId || opId.length < 2) return false;
  return ANOMALY_PREFIXES.has(opId.slice(0, 2).toUpperCase());
}

function getAnomalyMeta(opId) {
  if (!opId || opId.length < 2) return null;
  return ANOMALY_META[opId.slice(0, 2).toUpperCase()] || null;
}

// ── Tabla de operaciones — espejo de tabla_operacion.json ────────────────────
const OPS = {
  // ── Auth — Login ────────────────────────────────────────────────────────
  "OP001":         { name:"Login (email/password)",          gates:["HttpGate","DbGate"],                   module:"auth"     },
  "OP001_001":     { name:"Login — validar HTTP",            gates:["HttpGate"],                            module:"auth"     },
  "OP001_002":     { name:"Login — buscar usuario en DB",    gates:["DbGate"],                              module:"auth"     },
  "OP001_003":     { name:"Login — crear sesión en DB",      gates:["DbGate"],                              module:"auth"     },
  "OP001_004":     { name:"Login — alerta nuevo dispositivo",gates:["ModuleGate"],                          module:"auth"     },
  // ── Auth — Registro ─────────────────────────────────────────────────────
  "OP002":         { name:"Registro",                        gates:["HttpGate","DbGate"],                   module:"auth"     },
  "OP002_001":     { name:"Registro — validar HTTP",         gates:["HttpGate"],                            module:"auth"     },
  "OP002_002":     { name:"Registro — crear usuario",        gates:["DbGate"],                              module:"auth"     },
  "OP002_003":     { name:"Registro — crear identidad",      gates:["DbGate"],                              module:"auth"     },
  "OP002_004":     { name:"Registro — crear sesión",         gates:["DbGate"],                              module:"auth"     },
  "OP002_005":     { name:"Registro — email verificación",   gates:["ModuleGate"],                          module:"auth"     },
  // ── Auth — OAuth Google ─────────────────────────────────────────────────
  "OP003":         { name:"OAuth Google",                    gates:["HttpGate","DbGate","ModuleGate"],      module:"auth"     },
  "OP003_001":     { name:"OAuth Google — redirect",         gates:["HttpGate"],                            module:"auth"     },
  "OP003_002":     { name:"OAuth Google — token exchange",   gates:["ModuleGate"],                          module:"auth"     },
  "OP003_002_001": { name:"OAuth Google — fetch token",      gates:["ModuleGate"],                          module:"auth"     },
  "OP003_002_002": { name:"OAuth Google — userinfo",         gates:["ModuleGate"],                          module:"auth"     },
  "OP003_003":     { name:"OAuth Google — DB usuario",       gates:["DbGate"],                              module:"auth"     },
  "OP003_003_001": { name:"OAuth Google — lookup usuario",   gates:["DbGate"],                              module:"auth"     },
  "OP003_003_002": { name:"OAuth Google — link identidad",   gates:["DbGate"],                              module:"auth"     },
  "OP003_004":     { name:"OAuth Google — crear sesión",     gates:["DbGate"],                              module:"auth"     },
  // ── Auth — OAuth GitHub ─────────────────────────────────────────────────
  "OP004":         { name:"OAuth GitHub",                    gates:["HttpGate","DbGate","ModuleGate"],      module:"auth"     },
  "OP004_001":     { name:"OAuth GitHub — redirect",         gates:["HttpGate"],                            module:"auth"     },
  "OP004_002":     { name:"OAuth GitHub — token exchange",   gates:["ModuleGate"],                          module:"auth"     },
  "OP004_002_001": { name:"OAuth GitHub — fetch token",      gates:["ModuleGate"],                          module:"auth"     },
  "OP004_002_002": { name:"OAuth GitHub — profile",          gates:["ModuleGate"],                          module:"auth"     },
  "OP004_002_003": { name:"OAuth GitHub — emails",           gates:["ModuleGate"],                          module:"auth"     },
  "OP004_003":     { name:"OAuth GitHub — DB usuario",       gates:["DbGate"],                              module:"auth"     },
  "OP004_004":     { name:"OAuth GitHub — crear sesión",     gates:["DbGate"],                              module:"auth"     },
  // ── Auth — Passkey ──────────────────────────────────────────────────────
  "OP005":         { name:"Passkey — registro",              gates:["HttpGate","DbGate","ModuleGate"],      module:"auth"     },
  "OP005_001":     { name:"Passkey — register begin",        gates:["HttpGate","DbGate"],                   module:"auth"     },
  "OP005_001_001": { name:"Passkey — user lookup",           gates:["DbGate"],                              module:"auth"     },
  "OP005_001_002": { name:"Passkey — register options",      gates:["ModuleGate"],                          module:"auth"     },
  "OP005_002":     { name:"Passkey — register complete",     gates:["HttpGate","DbGate","ModuleGate"],      module:"auth"     },
  "OP005_002_001": { name:"Passkey — verify credential",     gates:["ModuleGate"],                          module:"auth"     },
  "OP005_002_002": { name:"Passkey — save credential",       gates:["DbGate"],                              module:"auth"     },
  "OP006":         { name:"Passkey — login",                 gates:["HttpGate","DbGate","ModuleGate"],      module:"auth"     },
  "OP006_001":     { name:"Passkey — login begin",           gates:["HttpGate"],                            module:"auth"     },
  "OP006_002":     { name:"Passkey — login complete",        gates:["HttpGate","DbGate","ModuleGate"],      module:"auth"     },
  "OP006_002_001": { name:"Passkey — credential lookup",     gates:["DbGate"],                              module:"auth"     },
  "OP006_002_002": { name:"Passkey — verify assertion",      gates:["ModuleGate"],                          module:"auth"     },
  "OP006_002_003": { name:"Passkey — session create",        gates:["DbGate"],                              module:"auth"     },
  // ── Auth — Email ────────────────────────────────────────────────────────
  "OP007":         { name:"Email transaccional",             gates:["ModuleGate"],                          module:"auth"     },
  "OP007_001":     { name:"Email — verificación",            gates:["ModuleGate"],                          module:"auth"     },
  "OP007_002":     { name:"Email — nuevo dispositivo",       gates:["ModuleGate"],                          module:"auth"     },
  "OP007_003":     { name:"Email — reset password",          gates:["ModuleGate"],                          module:"auth"     },
  "OP007_004":     { name:"Email — sesiones revocadas",      gates:["ModuleGate"],                          module:"auth"     },
  // ── Auth — Sesiones ─────────────────────────────────────────────────────
  "OP008":         { name:"Gestión de sesiones",             gates:["HttpGate","DbGate"],                   module:"auth"     },
  "OP008_001":     { name:"Sesión — logout",                 gates:["DbGate"],                              module:"auth"     },
  "OP008_002":     { name:"Sesión — refresh token",          gates:["HttpGate","DbGate"],                   module:"auth"     },
  "OP008_003":     { name:"Sesión — revocar una",            gates:["DbGate"],                              module:"auth"     },
  "OP008_004":     { name:"Sesión — revocar todas",          gates:["DbGate","ModuleGate"],                 module:"auth"     },
  // ── System ──────────────────────────────────────────────────────────────
  "OP009":         { name:"DB — inicialización",             gates:["BootGate","DbGate"],                   module:"system"   },
  "OP009_001":     { name:"DB — conexión",                   gates:["DbGate"],                              module:"system"   },
  "OP009_002":     { name:"DB — migraciones",                gates:["DbGate"],                              module:"system"   },
  "OP009_003":     { name:"DB — verificar tablas",           gates:["DbGate"],                              module:"system"   },
  "OP010":         { name:"Boot del sistema",                gates:["BootGate"],                            module:"system"   },
  "OP010_001":     { name:"Boot — fase 1: DB",               gates:["BootGate"],                            module:"system"   },
  "OP010_002":     { name:"Boot — fase 1: blueprints",       gates:["BootGate"],                            module:"system"   },
  "OP010_003":     { name:"Boot — fase 2: OAuth",            gates:["BootGate"],                            module:"system"   },
  "OP010_004":     { name:"Boot — fase 2: conductor",        gates:["BootGate"],                            module:"system"   },
  "OP010_005":     { name:"Boot — fase 2: tracer",           gates:["BootGate"],                            module:"system"   },
  // ── Auth — Páginas y endpoints REST (v4.0) ──────────────────────────────
  "OP011":         { name:"Auth — página login",             gates:["HttpGate"],                            module:"auth"     },
  "OP012":         { name:"Auth — página registro",          gates:["HttpGate"],                            module:"auth"     },
  "OP013":         { name:"Auth — página consent SSO",       gates:["HttpGate"],                            module:"auth"     },
  "OP014":         { name:"Auth — página dispositivos",      gates:["HttpGate"],                            module:"auth"     },
  "OP015":         { name:"Auth — OAuth complete",           gates:["HttpGate"],                            module:"auth"     },
  "OP016":         { name:"Auth — perfil (/me)",             gates:["HttpGate","DbGate"],                   module:"auth"     },
  "OP017":         { name:"Auth — verificar email",          gates:["HttpGate","DbGate"],                   module:"auth"     },
  "OP018":         { name:"Auth — reenviar verificación",    gates:["HttpGate","ModuleGate"],               module:"auth"     },
  "OP019":         { name:"Auth — reset password",           gates:["HttpGate","DbGate"],                   module:"auth"     },
  "OP034":         { name:"Auth — listar sesiones",          gates:["HttpGate","DbGate"],                   module:"auth"     },
  "OP035":         { name:"Auth — revocar sesión",           gates:["HttpGate","DbGate"],                   module:"auth"     },
  "OP036":         { name:"Auth — listar dispositivos",      gates:["HttpGate","DbGate"],                   module:"auth"     },
  "OP037":         { name:"Auth — consent SSO",              gates:["HttpGate"],                            module:"auth"     },
  "OP038":         { name:"Auth — grant producto",           gates:["HttpGate","DbGate"],                   module:"auth"     },
  "OP039":         { name:"Auth — refresh token",            gates:["HttpGate","DbGate"],                   module:"auth"     },
  // ── Lifebound ───────────────────────────────────────────────────────────
  "OP020":         { name:"Lifebound — iniciar sesión",      gates:["HttpGate"],                            module:"lifebound"},
  "OP021":         { name:"Lifebound — recibir fotos",       gates:["HttpGate"],                            module:"lifebound"},
  "OP022":         { name:"Lifebound — seleccionar patrón",  gates:["HttpGate"],                            module:"lifebound"},
  "OP023":         { name:"Lifebound — resolver slots",      gates:["HttpGate"],                            module:"lifebound"},
  "OP024":         { name:"Lifebound — transformar fotos",   gates:["HttpGate"],                            module:"lifebound"},
  "OP025":         { name:"Lifebound — generar PDF",         gates:["HttpGate","ModuleGate"],               module:"lifebound"},
  "OP025_001":     { name:"Lifebound — páginas intro",       gates:["ModuleGate"],                          module:"lifebound"},
  "OP025_002":     { name:"Lifebound — páginas evidencia",   gates:["ModuleGate"],                          module:"lifebound"},
  "OP025_003":     { name:"Lifebound — merge PDF",           gates:["ModuleGate"],                          module:"lifebound"},
  "OP026":         { name:"Lifebound — estado sesión",       gates:["HttpGate"],                            module:"lifebound"},
  "OP027":         { name:"Lifebound — limpiar sesión",      gates:["HttpGate"],                            module:"lifebound"},
  "OP028":         { name:"Lifebound — listar templates",    gates:["HttpGate"],                            module:"lifebound"},
  "OP029":         { name:"Lifebound — preview página",      gates:["HttpGate","ModuleGate"],               module:"lifebound"},
  // ── Frontend (v4.0) ─────────────────────────────────────────────────────
  "OP030":         { name:"Frontend — home",                 gates:["HttpGate"],                            module:"frontend" },
  "OP031":         { name:"Frontend — HUD",                  gates:["HttpGate"],                            module:"frontend" },
  "OP032":         { name:"Frontend — Lifebound app",        gates:["HttpGate"],                            module:"frontend" },
  "OP033":         { name:"API — anuncios",                  gates:["HttpGate"],                            module:"frontend" },
  // ── Dashboard ───────────────────────────────────────────────────────────
  "OP099":         { name:"Dashboard — poll",                gates:["HttpGate"],                            module:"dashboard"},
  "OP099_001":     { name:"Dashboard — status",              gates:["HttpGate"],                            module:"dashboard"},
  "OP099_002":     { name:"Dashboard — sesiones",            gates:["HttpGate"],                            module:"dashboard"},
  "OP099_003":     { name:"Dashboard — usuarios",            gates:["HttpGate"],                            module:"dashboard"},
  "OP099_004":     { name:"Dashboard — actividad",           gates:["HttpGate"],                            module:"dashboard"},
  "OP099_005":     { name:"Dashboard — export",              gates:["HttpGate"],                            module:"dashboard"},
};

// ── Helpers de ops ────────────────────────────────────────────────────────────

function opLabel(opId) {
  if (!opId) return "—";
  const meta = getAnomalyMeta(opId);
  if (meta) return `${meta.label} (${opId})`;
  return OPS[opId]?.name || opId;
}

function opModule(opId) {
  if (!opId) return "unknown";
  if (isAnomalyOp(opId)) return "discovery";
  return OPS[opId]?.module || "auth";
}

function buildOpChain(opId) {
  if (!opId) return [];
  const parts = opId.split("_");
  const chain = [];
  for (let i = 1; i <= parts.length; i++) {
    const id = parts.slice(0, i).join("_");
    const op = OPS[id];
    chain.push({
      id,
      name:   op?.name   || id,
      gates:  op?.gates  || [],
      module: op?.module || "—",
    });
  }
  return chain;
}