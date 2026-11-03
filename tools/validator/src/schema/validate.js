import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";
import { buildSchemas } from "./build.js";
import { isBase64 } from "./base64.js";

let compiled;
let numberLiterals = new Map();
// JSON has no binary64 limit. Check integrality and sign from the original
// spelling, so rounding and underflow cannot turn a fraction into an integer.
function numericShape(constraints, data, _schema, context) {
  const literal = numberLiterals.get(context.instancePath);
  if (!literal || typeof data !== "number") return true;
  const [mantissa, exponent = "0"] = literal.replace(/^-/, "").split(/[eE]/);
  const [whole, fraction = ""] = mantissa.split(".");
  const digits = whole + fraction;
  const zero = /^0+$/.test(digits);
  const scale = Number(exponent) - fraction.length;
  const integral = zero || scale >= 0 || scale + /0*$/.exec(digits)[0].length >= 0;
  const roundedFraction = constraints.integer && !integral && (Number.isInteger(data) || !Number.isFinite(data));
  const lostNegative = constraints.nonnegative && !zero && literal.startsWith("-") && data >= 0;
  return !roundedFraction && !lostNegative;
}

function schemas() {
  if (compiled) return compiled;
  const ajv = new Ajv2020({ allErrors: true, strict: false, strictNumbers: false, verbose: true });
  addFormats(ajv);
  ajv.addFormat("asr-base64", { type: "string", validate: isBase64 });
  ajv.addKeyword({ keyword: "asrNumber", schemaType: "object", errors: false, validate: numericShape });
  // Separate object identities keep requirement labels local to each schema node.
  const definitions = JSON.parse(JSON.stringify(buildSchemas()));
  const labels = new WeakMap();
  function label(node, inherited) {
    if (!node || typeof node !== "object") return;
    const types = Array.isArray(node.type) ? node.type : [node.type];
    if (types.some((type) => ["integer", "number"].includes(type))) node.asrNumber = { integer: types.includes("integer"), nonnegative: node.minimum === 0 };
    const requirement = node["x-asr"] ?? inherited;
    labels.set(node, requirement);
    for (const [key, child] of Object.entries(node)) {
      if (key === "$defs") Object.values(child).forEach((value) => label(value));
      else if (!["const", "enum"].includes(key)) label(child, requirement);
    }
  }
  for (const schema of Object.values(definitions)) {
    label(schema);
    ajv.addSchema(schema);
  }
  compiled = { labels, validators: Object.fromEntries(Object.entries(definitions).map(([name, schema]) => [name, ajv.getSchema(schema.$id)])) };
  return compiled;
}

export function validateWithSchema(kind, value, numbers = new Map()) {
  const { validators, labels } = schemas();
  numberLiterals = numbers;
  const validate = validators[kind];
  if (!validate) throw new Error(`Unknown schema: ${kind}`);
  let errors;
  try {
    if (validate(value)) return [];
    errors = validate.errors;
  } finally {
    numberLiterals = new Map();
    // Ajv's verbose diagnostics retain original data until explicitly released.
    validate.errors = null;
  }
  const alternatives = errors.filter((error) => ["anyOf", "oneOf"].includes(error.keyword));
  return errors.filter((error) =>
    !["if", "propertyNames"].includes(error.keyword) &&
    !alternatives.some((parent) => error.schemaPath.startsWith(parent.schemaPath + "/")),
  ).map((error) => {
    let message = error.message;
    if (error.keyword === "asrNumber") message = "must have the required numeric shape without rounding";
    if (error.keyword === "not") {
      message = error.schema.required
        ? `must not contain both ${error.schema.required.join(" and ")}`
        : "must not contain encrypted reasoning text or summary";
    }
    if (error.keyword === "anyOf" && error.schema.every((branch) => branch.required)) {
      message = `must contain ${error.schema.map((branch) => branch.required.join(" and ")).join(" or ")}`;
    }
    return {
      severity: "error", ...(kind === "manifest" ? {} : { requirement: labels.get(error.parentSchema) ?? (kind === "annotation" ? "ASR-062" : "ASR-069") }),
      code: `schema.${error.keyword}`, pointer: error.instancePath, message,
    };
  });
}
