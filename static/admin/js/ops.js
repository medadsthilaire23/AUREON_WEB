// js/ops.js
// ── Mapa estático de operaciones + helpers de gate ────────────────────────────
// Fuente de verdad para nombres, gates y módulos de cada OP.
// Sincronizar con shared/control/operation_gates.py al añadir nuevas OPs.

const OPS = {
  // ── Auth ──────────────────────────────────────────────────────────────────
  "OP001":         { name:"Login (email/password)",           gates:["H","D"],     module:"auth"      },
  "OP001_001":     { name:"Login — validar HTTP",             gates:["H"],         module:"auth"      },
  "OP001_002":     { name:"Login — buscar usuario en DB",     gates:["D"],         module:"auth"      },
  "OP001_003":     { name:"Login — crear sesión en DB",       gates:["D"],         module:"auth"      },
  "OP001_004":     { name:"Login — alerta nuevo dispositivo", gates:["M"],         module:"auth"      },
  "OP002":         { name:"Registro",                         gates:["H","D"],     module:"auth"      },
  "OP002_001":     { name:"Registro — validar HTTP",          gates:["H"],         module:"auth"      },
  "OP002_002":     { name:"Registro — crear usuario",         gates:["D"],         module:"auth"      },
  "OP002_003":     { name:"Registro — crear identidad",       gates:["D"],         module:"auth"      },
  "OP002_004":     { name:"Registro — crear sesión",          gates:["D"],         module:"auth"      },
  "OP002_005":     { name:"Registro — email verificación",    gates:["M"],         module:"auth"      },
  "OP003":         { name:"OAuth Google",                     gates:["H","D","M"], module:"auth"      },
  "OP003_001":     { name:"OAuth Google — redirect",          gates:["H"],         module:"auth"      },
  "OP003_002":     { name:"OAuth Google — token exchange",    gates:["M"],         module:"auth"      },
  "OP003_002_001": { name:"OAuth Google — fetch token",       gates:["M"],         module:"auth"      },
  "OP003_002_002": { name:"OAuth Google — userinfo",          gates:["M"],         module:"auth"      },
  "OP003_003":     { name:"OAuth Google — DB usuario",        gates:["D"],         module:"auth"      },
  "OP003_003_001": { name:"OAuth Google — lookup usuario",    gates:["D"],         module:"auth"      },
  "OP003_003_002": { name:"OAuth Google — link identidad",    gates:["D"],         module:"auth"      },
  "OP003_004":     { name:"OAuth Google — crear sesión",      gates:["D"],         module:"auth"      },
  "OP004":         { name:"OAuth GitHub",                     gates:["H","D","M"], module:"auth"      },
  "OP004_001":     { name:"OAuth GitHub — redirect",          gates:["H"],         module:"auth"      },
  "OP004_002":     { name:"OAuth GitHub — token exchange",    gates:["M"],         module:"auth"      },
  "OP004_002_001": { name:"OAuth GitHub — fetch token",       gates:["M"],         module:"auth"      },
  "OP004_002_002": { name:"OAuth GitHub — profile",           gates:["M"],         module:"auth"      },
  "OP004_002_003": { name:"OAuth GitHub — emails",            gates:["M"],         module:"auth"      },
  "OP004_003":     { name:"OAuth GitHub — DB usuario",        gates:["D"],         module:"auth"      },
  "OP004_004":     { name:"OAuth GitHub — crear sesión",      gates:["D"],         module:"auth"      },
  "OP005":         { name:"Passkey — registro",               gates:["H","D","M"], module:"auth"      },
  "OP006":         { name:"Passkey — login",                  gates:["H","D","M"], module:"auth"      },
  "OP007":         { name:"Email transaccional",              gates:["M"],         module:"auth"      },
  "OP007_001":     { name:"Email — verificación",             gates:["M"],         module:"auth"      },
  "OP007_002":     { name:"Email — nuevo dispositivo",        gates:["M"],         module:"auth"      },
  "OP007_003":     { name:"Email — reset password",           gates:["M"],         module:"auth"      },
  "OP007_004":     { name:"Email — sesiones revocadas",       gates:["M"],         module:"auth"      },
  "OP008":         { name:"Gestión de sesiones",              gates:["H","D"],     module:"auth"      },
  "OP008_001":     { name:"Sesión — logout",                  gates:["D"],         module:"auth"      },
  "OP008_002":     { name:"Sesión — refresh token",           gates:["H","D"],     module:"auth"      },
  "OP008_003":     { name:"Sesión — revocar una",             gates:["D"],         module:"auth"      },
  "OP008_004":     { name:"Sesión — revocar todas",           gates:["D","M"],     module:"auth"      },

  // ── System ────────────────────────────────────────────────────────────────
  "OP009":         { name:"DB — inicialización",              gates:["B","D"],     module:"system"    },
  "OP009_001":     { name:"DB — conexión",                    gates:["D"],         module:"system"    },
  "OP009_002":     { name:"DB — migraciones",                 gates:["D"],         module:"system"    },
  "OP009_003":     { name:"DB — verificar tablas",            gates:["D"],         module:"system"    },
  "OP010":         { name:"Boot del sistema",                 gates:["B"],         module:"system"    },
  "OP010_001":     { name:"Boot — fase 1: DB",                gates:["B"],         module:"system"    },
  "OP010_002":     { name:"Boot — fase 1: blueprints",        gates:["B"],         module:"system"    },
  "OP010_003":     { name:"Boot — fase 2: OAuth",             gates:["B"],         module:"system"    },
  "OP010_004":     { name:"Boot — fase 2: conductor",         gates:["B"],         module:"system"    },
  "OP010_005":     { name:"Boot — fase 2: tracer",            gates:["B"],         module:"system"    },

  // ── Lifebound ─────────────────────────────────────────────────────────────
  "OP020":         { name:"Lifebound — iniciar sesión",       gates:["H"],         module:"lifebound" },
  "OP021":         { name:"Lifebound — recibir fotos",        gates:["H"],         module:"lifebound" },
  "OP022":         { name:"Lifebound — seleccionar patrón",   gates:["H"],         module:"lifebound" },
  "OP023":         { name:"Lifebound — resolver slots",       gates:["H"],         module:"lifebound" },
  "OP024":         { name:"Lifebound — transformar fotos",    gates:["H"],         module:"lifebound" },
  "OP025":         { name:"Lifebound — generar PDF",          gates:["H","M"],     module:"lifebound" },
  "OP025_001":     { name:"Lifebound — páginas intro",        gates:["M"],         module:"lifebound" },
  "OP025_002":     { name:"Lifebound — páginas evidencia",    gates:["M"],         module:"lifebound" },
  "OP025_003":     { name:"Lifebound — merge PDF",            gates:["M"],         module:"lifebound" },
  "OP026":         { name:"Lifebound — estado sesión",        gates:["H"],         module:"lifebound" },
  "OP027":         { name:"Lifebound — limpiar sesión",       gates:["H"],         module:"lifebound" },
  "OP028":         { name:"Lifebound — listar templates",     gates:["H"],         module:"lifebound" },
  "OP029":         { name:"Lifebound — preview página",       gates:["H","M"],     module:"lifebound" },

  // ── Dashboard (interno) ───────────────────────────────────────────────────
  "OP099":         { name:"Dashboard — poll",                 gates:["H"],         module:"dashboard" },
  "OP099_001":     { name:"Dashboard — status",               gates:["H"],         module:"dashboard" },
  "OP099_002":     { name:"Dashboard — sesiones",             gates:["H"],         module:"dashboard" },
  "OP099_003":     { name:"Dashboard — usuarios",             gates:["H"],         module:"dashboard" },
  "OP099_004":     { name:"Dashboard — actividad",            gates:["H"],         module:"dashboard" },
  "OP099_005":     { name:"Dashboard — export",               gates:["H"],         module:"dashboard" },
};

/** Nombre completo del gate por alias */
const GATE_FULL = { H: "HttpGate", D: "DbGate", M: "ModuleGate", B: "BootGate" };

/** Nombre legible de una operación */
function opLabel(opId)  { return OPS[opId]?.name   || opId || "—"; }

/** Módulo al que pertenece una operación */
function opModule(opId) { return OPS[opId]?.module  || "auth"; }

/**
 * Construye la cadena de ancestros de un op_id.
 * Ej: "OP003_002_001" → [OP003, OP003_002, OP003_002_001]
 */
function buildOpChain(opId) {
  if (!opId) return [];
  const parts = opId.split("_");
  return parts.map((_, i) => {
    const id = parts.slice(0, i + 1).join("_");
    const op = OPS[id];
    return { id, name: op?.name || id, gates: op?.gates || [], module: op?.module || "—" };
  });
}

/** Renderiza una gate-tag coloreada */
function gateTag(alias) {
  const cls  = ["H","D","M","B"].includes(alias) ? alias : "def";
  const name = GATE_FULL[alias] || alias;
  return `<span class="gate-tag ${cls}">${name}</span>`;
}