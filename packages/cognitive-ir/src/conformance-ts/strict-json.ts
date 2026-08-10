const SAFE_INTEGER = 9_007_199_254_740_991;

export class StrictJsonError extends Error {
  code: string;
  pointer: string;

  constructor(code: string, pointer = "") {
    super(code);
    this.name = "StrictJsonError";
    this.code = code;
    this.pointer = pointer;
  }
}

function escapePointer(value: string) {
  return value.replaceAll("~", "~0").replaceAll("/", "~1");
}

class Parser {
  text: string;
  index = 0;

  constructor(bytes: Uint8Array) {
    if (bytes.length >= 3 && bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf) {
      throw new StrictJsonError("json.bom");
    }
    try {
      this.text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    } catch {
      throw new StrictJsonError("json.invalid_utf8");
    }
  }

  parse() {
    const result = this.value("");
    this.space();
    if (this.index !== this.text.length) throw new StrictJsonError("json.invalid_syntax");
    return result;
  }

  space() {
    while (this.index < this.text.length && " \t\r\n".includes(this.text[this.index])) this.index++;
  }

  value(pointer: string): unknown {
    this.space();
    const ch = this.text[this.index];
    if (ch === "{") return this.object(pointer);
    if (ch === "[") return this.array(pointer);
    if (ch === '"') return this.string(pointer);
    if (ch === "t" && this.take("true")) return true;
    if (ch === "f" && this.take("false")) return false;
    if (ch === "n" && this.take("null")) return null;
    if (ch === "-" || (ch >= "0" && ch <= "9")) return this.number(pointer);
    throw new StrictJsonError("json.invalid_syntax", pointer);
  }

  take(token: string) {
    if (this.text.slice(this.index, this.index + token.length) !== token) return false;
    this.index += token.length;
    return true;
  }

  object(pointer: string) {
    const result: Record<string, unknown> = {};
    const seen = new Set<string>();
    this.index++;
    this.space();
    if (this.text[this.index] === "}") { this.index++; return result; }
    while (true) {
      this.space();
      if (this.text[this.index] !== '"') throw new StrictJsonError("json.invalid_syntax", pointer);
      const key = this.string(pointer);
      const child = `${pointer}/${escapePointer(key)}`;
      if (seen.has(key)) throw new StrictJsonError("json.duplicate_member", child);
      seen.add(key);
      this.space();
      if (this.text[this.index++] !== ":") throw new StrictJsonError("json.invalid_syntax", child);
      result[key] = this.value(child);
      this.space();
      const delimiter = this.text[this.index++];
      if (delimiter === "}") return result;
      if (delimiter !== ",") throw new StrictJsonError("json.invalid_syntax", pointer);
    }
  }

  array(pointer: string) {
    const result: unknown[] = [];
    this.index++;
    this.space();
    if (this.text[this.index] === "]") { this.index++; return result; }
    while (true) {
      result.push(this.value(`${pointer}/${result.length}`));
      this.space();
      const delimiter = this.text[this.index++];
      if (delimiter === "]") return result;
      if (delimiter !== ",") throw new StrictJsonError("json.invalid_syntax", pointer);
    }
  }

  string(pointer: string) {
    this.index++;
    let result = "";
    while (this.index < this.text.length) {
      const ch = this.text[this.index++];
      if (ch === '"') return result;
      if (ch === "\\") {
        const escaped = this.text[this.index++];
        const literals: Record<string, string> = { '"': '"', "\\": "\\", "/": "/", b: "\b", f: "\f", n: "\n", r: "\r", t: "\t" };
        if (escaped in literals) { result += literals[escaped]; continue; }
        if (escaped !== "u") throw new StrictJsonError("json.invalid_escape", pointer);
        const first = this.hex(pointer);
        if (first >= 0xd800 && first <= 0xdbff) {
          if (this.text.slice(this.index, this.index + 2) !== "\\u") throw new StrictJsonError("json.invalid_unicode_scalar", pointer);
          this.index += 2;
          const second = this.hex(pointer);
          if (second < 0xdc00 || second > 0xdfff) throw new StrictJsonError("json.invalid_unicode_scalar", pointer);
          result += String.fromCodePoint(0x10000 + ((first - 0xd800) << 10) + second - 0xdc00);
        } else if (first >= 0xdc00 && first <= 0xdfff) {
          throw new StrictJsonError("json.invalid_unicode_scalar", pointer);
        } else {
          result += String.fromCharCode(first);
        }
        continue;
      }
      if (ch.charCodeAt(0) < 0x20) throw new StrictJsonError("json.invalid_syntax", pointer);
      const code = ch.charCodeAt(0);
      if (code >= 0xd800 && code <= 0xdbff) {
        const second = this.text.charCodeAt(this.index);
        if (second < 0xdc00 || second > 0xdfff) throw new StrictJsonError("json.invalid_unicode_scalar", pointer);
        result += ch + this.text[this.index++];
      } else if (code >= 0xdc00 && code <= 0xdfff) {
        throw new StrictJsonError("json.invalid_unicode_scalar", pointer);
      } else {
        result += ch;
      }
    }
    throw new StrictJsonError("json.invalid_syntax", pointer);
  }

  hex(pointer: string) {
    const token = this.text.slice(this.index, this.index + 4);
    if (!/^[0-9a-fA-F]{4}$/.test(token)) throw new StrictJsonError("json.invalid_escape", pointer);
    this.index += 4;
    return Number.parseInt(token, 16);
  }

  number(pointer: string) {
    const rest = this.text.slice(this.index);
    const match = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/.exec(rest);
    if (!match) throw new StrictJsonError("json.invalid_number", pointer);
    const token = match[0];
    this.index += token.length;
    const value = Number(token);
    if (!Number.isFinite(value)) throw new StrictJsonError("json.invalid_number", pointer);
    // The profile's unsafe-integer rule applies to integer JSON tokens.  A
    // fractional/exponent token is an IEEE-754 number even when its resulting
    // mathematical value happens to be integral (JCS includes 1e21 vectors).
    if (!/[.eE]/.test(token) && Number.isInteger(value) && Math.abs(value) > SAFE_INTEGER) throw new StrictJsonError("json.unsafe_integer", pointer);
    return value;
  }
}

export function strictParse(bytes: Uint8Array): unknown {
  return new Parser(bytes).parse();
}

export function canonicalize(value: unknown): string {
  if (value === null || typeof value === "boolean" || typeof value === "string") return JSON.stringify(value);
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new StrictJsonError("json.invalid_number");
    return JSON.stringify(Object.is(value, -0) ? 0 : value);
  }
  if (Array.isArray(value)) return `[${value.map(canonicalize).join(",")}]`;
  if (typeof value === "object") {
    const object = value as Record<string, unknown>;
    return `{${Object.keys(object).sort().map((key) => `${JSON.stringify(key)}:${canonicalize(object[key])}`).join(",")}}`;
  }
  throw new StrictJsonError("json.invalid_value");
}
