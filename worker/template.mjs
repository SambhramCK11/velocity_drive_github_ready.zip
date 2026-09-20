/**
 * A renderer for the Jinja subset app/templates uses.
 *
 * The templates stay one set of files rendered by both runtimes: Jinja under
 * Flask, this under the Worker. Hand-porting ten templates to JS would have left
 * two copies of every page to keep in step, and the first edit to one of them
 * would have made the two surfaces disagree.
 *
 * Supported, because it is what the templates use:
 *
 *   {{ expr }}                          escaped output
 *   {% if %} {% elif %} {% else %} {% endif %}
 *   {% for x in items %} {% endfor %}   with `loop.index`, `loop.first`, `loop.last`
 *   {% extends "base.html" %}           single inheritance
 *   {% block name %} … {% endblock %}   overridden by the child
 *   {% include "_card.html" %}          rendered with the current context
 *   {% set x = expr %}
 *   {# comments #}
 *   operators: or and not == != < <= > >= in, "not in", "is defined"
 *   A if COND else B                    inline conditional
 *   filters: money money2 tojson format round int float length join
 *            lower upper title trim default abs
 *   paths: a.b, a['b'], a[0], a.b(args)
 *
 * Anything else throws at compile time rather than rendering something subtly
 * wrong — a loud failure is easier to find than a silently empty price.
 */

/* ------------------------------------------------------------------ */
/* Escaping                                                            */
/* ------------------------------------------------------------------ */

// MarkupSafe's exact table: &#34; and &#39;, not &quot; and &apos;.
const ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&#34;', "'": '&#39;' };

/** A value a filter has already made safe; escaping passes it through. */
export class Safe {
  constructor(value) {
    this.value = String(value);
  }

  toString() {
    return this.value;
  }
}

export function escapeHtml(value) {
  if (value instanceof Safe) return value.value;
  if (value === null || value === undefined) return '';
  return String(value).replace(/[&<>"']/g, (c) => ESCAPES[c]);
}

/* ------------------------------------------------------------------ */
/* Filters                                                            */
/* ------------------------------------------------------------------ */

/** Group thousands and fix the decimals, as app/__init__.py's money filters. */
function formatMoney(value, places) {
  const number = Number(value);
  if (!Number.isFinite(number)) return value === null || value === undefined ? '' : String(value);
  return number.toLocaleString('en-US', {
    minimumFractionDigits: places,
    maximumFractionDigits: places,
  });
}

/** printf-style %s / %d / %f / %.Nf, which is all '…'|format(x) needs here. */
function applyFormat(template, args) {
  let index = 0;
  return String(template).replace(/%(?:(\d+)\$)?([-+ 0]*)(\d+)?(?:\.(\d+))?([sdifg%])/g,
    (_, position, flags, width, precision, kind) => {
      if (kind === '%') return '%';
      const value = args[position ? Number(position) - 1 : index++];
      let text;
      if (kind === 's') {
        text = value === null || value === undefined ? 'None' : String(value);
      } else if (kind === 'd' || kind === 'i') {
        text = String(Math.trunc(Number(value)));
      } else {
        text = Number(value).toFixed(precision === undefined ? 6 : Number(precision));
      }
      if (width && text.length < Number(width)) {
        text = flags.includes('-')
          ? text.padEnd(Number(width))
          : text.padStart(Number(width), flags.includes('0') ? '0' : ' ');
      }
      return text;
    });
}

/**
 * Jinja's tojson: JSON, with the characters that could break out of a script or
 * an attribute escaped as \\uXXXX, and the result marked safe.
 */
function toJson(value) {
  const json = JSON.stringify(value === undefined ? null : value)
    .replace(/</g, '\\u003c')
    .replace(/>/g, '\\u003e')
    .replace(/&/g, '\\u0026')
    .replace(/'/g, '\\u0027');
  return new Safe(json);
}

const FILTERS = {
  money: (v) => formatMoney(v, 0),
  money2: (v) => formatMoney(v, 2),
  tojson: toJson,
  format: (template, ...args) => applyFormat(template, args),
  round: (v, digits = 0) => {
    const factor = 10 ** digits;
    // Jinja's round defaults to 'common' rounding: halves away from zero.
    const scaled = Number(v) * factor;
    const rounded = scaled < 0 ? -Math.round(-scaled) : Math.round(scaled);
    return digits === 0 ? rounded : rounded / factor;
  },
  int: (v, fallback = 0) => {
    const n = Number.parseInt(Number(v), 10);
    return Number.isNaN(n) ? fallback : n;
  },
  float: (v, fallback = 0.0) => {
    const n = Number.parseFloat(v);
    return Number.isNaN(n) ? fallback : n;
  },
  length: (v) => (v === null || v === undefined ? 0 : v.length ?? Object.keys(v).length),
  join: (v, separator = '') => (Array.isArray(v) ? v.join(separator) : String(v ?? '')),
  lower: (v) => String(v ?? '').toLowerCase(),
  upper: (v) => String(v ?? '').toUpperCase(),
  title: (v) =>
    String(v ?? '').replace(/\w+/g, (w) => w[0].toUpperCase() + w.slice(1).toLowerCase()),
  trim: (v) => String(v ?? '').trim(),
  abs: (v) => Math.abs(Number(v)),
  default: (v, fallback = '') => (v === undefined || v === null || v === false ? fallback : v),
  safe: (v) => new Safe(v ?? ''),
};

/* ------------------------------------------------------------------ */
/* Expression lexer                                                    */
/* ------------------------------------------------------------------ */

const OPERATORS = [
  '==', '!=', '<=', '>=', '//', '**', '<', '>', '=', '~', '(', ')', '[', ']', '{', '}',
  ',', '.', '|', '+', '-', '*', '/', '%', ':',
];

function lex(source) {
  const tokens = [];
  let i = 0;

  while (i < source.length) {
    const ch = source[i];

    if (/\s/.test(ch)) {
      i += 1;
      continue;
    }
    if (ch === '"' || ch === "'") {
      const end = source.indexOf(ch, i + 1);
      if (end === -1) throw new Error(`Unterminated string in expression: ${source}`);
      tokens.push({ type: 'string', value: source.slice(i + 1, end) });
      i = end + 1;
      continue;
    }
    if (/[0-9]/.test(ch)) {
      const match = /^[0-9]+(\.[0-9]+)?/.exec(source.slice(i));
      tokens.push({ type: 'number', value: Number(match[0]) });
      i += match[0].length;
      continue;
    }
    if (/[A-Za-z_]/.test(ch)) {
      const match = /^[A-Za-z_]\w*/.exec(source.slice(i));
      tokens.push({ type: 'name', value: match[0] });
      i += match[0].length;
      continue;
    }
    const operator = OPERATORS.find((op) => source.startsWith(op, i));
    if (!operator) throw new Error(`Unexpected character '${ch}' in expression: ${source}`);
    tokens.push({ type: 'op', value: operator });
    i += operator.length;
  }
  return tokens;
}

/* ------------------------------------------------------------------ */
/* Expression parser                                                   */
/* ------------------------------------------------------------------ */

const UNDEFINED = Symbol('undefined');

class ExpressionParser {
  constructor(source) {
    this.source = source;
    this.tokens = lex(source);
    this.position = 0;
  }

  peek(offset = 0) {
    return this.tokens[this.position + offset];
  }

  next() {
    return this.tokens[this.position++];
  }

  at(type, value) {
    const token = this.peek();
    return token && token.type === type && (value === undefined || token.value === value);
  }

  eat(type, value) {
    if (this.at(type, value)) {
      this.position += 1;
      return true;
    }
    return false;
  }

  expect(type, value) {
    if (!this.eat(type, value)) {
      throw new Error(`Expected ${value ?? type} in expression: ${this.source}`);
    }
  }

  parse() {
    const node = this.parseConditional();
    if (this.position < this.tokens.length) {
      throw new Error(`Unexpected trailing input in expression: ${this.source}`);
    }
    return node;
  }

  /** `A if COND else B`, and Jinja's `A if COND` with an implicit empty else. */
  parseConditional() {
    const body = this.parseOr();
    if (!this.at('name', 'if')) return body;
    this.next();
    const test = this.parseOr();
    let alternate = null;
    if (this.eat('name', 'else')) alternate = this.parseOr();
    return (ctx) => (truthy(test(ctx)) ? body(ctx) : alternate ? alternate(ctx) : '');
  }

  parseOr() {
    let left = this.parseAnd();
    while (this.at('name', 'or')) {
      this.next();
      const right = this.parseAnd();
      const previous = left;
      left = (ctx) => {
        const value = previous(ctx);
        return truthy(value) ? value : right(ctx);
      };
    }
    return left;
  }

  parseAnd() {
    let left = this.parseNot();
    while (this.at('name', 'and')) {
      this.next();
      const right = this.parseNot();
      const previous = left;
      left = (ctx) => {
        const value = previous(ctx);
        return truthy(value) ? right(ctx) : value;
      };
    }
    return left;
  }

  parseNot() {
    if (this.at('name', 'not')) {
      this.next();
      const operand = this.parseNot();
      return (ctx) => !truthy(operand(ctx));
    }
    return this.parseComparison();
  }

  parseComparison() {
    const left = this.parseMath();

    // `is defined` / `is not defined`
    if (this.at('name', 'is')) {
      this.next();
      const negated = this.eat('name', 'not');
      const test = this.next();
      if (!test || test.type !== 'name' || !['defined', 'none', 'undefined'].includes(test.value)) {
        throw new Error(`Unsupported test 'is ${test?.value}' in: ${this.source}`);
      }
      return (ctx) => {
        const value = left(ctx);
        const defined = value !== UNDEFINED && value !== undefined;
        const result = test.value === 'none' ? value === null : defined;
        return negated ? !result : result;
      };
    }

    // `in` / `not in`
    if (this.at('name', 'in') || (this.at('name', 'not') && this.peek(1)?.value === 'in')) {
      const negated = this.eat('name', 'not');
      this.expect('name', 'in');
      const container = this.parseMath();
      return (ctx) => {
        const needle = left(ctx);
        const haystack = container(ctx);
        let found = false;
        if (Array.isArray(haystack)) found = haystack.includes(needle);
        else if (typeof haystack === 'string') found = haystack.includes(String(needle));
        else if (haystack && typeof haystack === 'object') found = needle in haystack;
        return negated ? !found : found;
      };
    }

    const token = this.peek();
    if (token?.type === 'op' && ['==', '!=', '<', '<=', '>', '>='].includes(token.value)) {
      this.next();
      const right = this.parseMath();
      const op = token.value;
      return (ctx) => {
        const a = normalise(left(ctx));
        const b = normalise(right(ctx));
        switch (op) {
          // Loose equality, as Jinja compares an int id against a string one.
          case '==': return a == b; // eslint-disable-line eqeqeq
          case '!=': return a != b; // eslint-disable-line eqeqeq
          case '<': return a < b;
          case '<=': return a <= b;
          case '>': return a > b;
          default: return a >= b;
        }
      };
    }
    return left;
  }

  parseMath() {
    let left = this.parseTerm();

    // Jinja's ~ concatenates, converting each side with str().
    while (this.at('op', '~')) {
      this.next();
      const right = this.parseTerm();
      const previous = left;
      left = (ctx) => `${stringify(previous(ctx))}${stringify(right(ctx))}`;
    }

    while (this.at('op', '+') || this.at('op', '-')) {
      const op = this.next().value;
      const right = this.parseTerm();
      const previous = left;
      left = (ctx) => {
        const a = previous(ctx);
        const b = right(ctx);
        if (op === '+') {
          // Jinja's + concatenates strings and adds numbers.
          if (typeof a === 'string' || typeof b === 'string') return `${a}${b}`;
          return Number(a) + Number(b);
        }
        return Number(a) - Number(b);
      };
    }
    return left;
  }

  parseTerm() {
    let left = this.parseFiltered();
    while (this.at('op', '*') || this.at('op', '/') || this.at('op', '//') || this.at('op', '%')) {
      const op = this.next().value;
      const right = this.parseFiltered();
      const previous = left;
      left = (ctx) => {
        const a = Number(previous(ctx));
        const b = Number(right(ctx));
        if (op === '*') return a * b;
        if (op === '/') return a / b;
        if (op === '//') return Math.floor(a / b);
        return a % b;
      };
    }
    return left;
  }

  parseFiltered() {
    let value = this.parseUnary();
    while (this.at('op', '|')) {
      this.next();
      const nameToken = this.next();
      if (!nameToken || nameToken.type !== 'name') {
        throw new Error(`Expected a filter name in: ${this.source}`);
      }
      const filter = FILTERS[nameToken.value];
      if (!filter) {
        throw new Error(`Unsupported filter '${nameToken.value}' in: ${this.source}`);
      }
      const args = this.at('op', '(') ? this.parseArguments() : { positional: [], keywords: [] };
      const previous = value;
      value = (ctx) =>
        filter(resolve(previous(ctx)), ...ExpressionParser.evaluateArguments(args, ctx));
    }
    return value;
  }

  parseUnary() {
    if (this.at('op', '-')) {
      this.next();
      const operand = this.parseUnary();
      return (ctx) => -Number(operand(ctx));
    }
    return this.parsePrimary();
  }

  /**
   * Call arguments, positional and keyword.
   *
   * Keyword arguments exist for url_for('static', filename='…'), which every
   * template uses. They are collected into one object passed as a trailing
   * argument, so a JS function receives (…positional, kwargs).
   */
  parseArguments() {
    this.expect('op', '(');
    const positional = [];
    const keywords = [];

    if (!this.at('op', ')')) {
      do {
        if (this.at('name') && this.peek(1)?.type === 'op' && this.peek(1).value === '=') {
          const name = this.next().value;
          this.next(); // '='
          keywords.push([name, this.parseConditional()]);
        } else {
          positional.push(this.parseConditional());
        }
      } while (this.eat('op', ','));
    }
    this.expect('op', ')');
    return { positional, keywords };
  }

  /** Evaluate an argument list against a context. */
  static evaluateArguments({ positional, keywords }, ctx) {
    const values = positional.map((arg) => resolve(arg(ctx)));
    if (keywords.length > 0) {
      const kwargs = {};
      for (const [name, expr] of keywords) kwargs[name] = resolve(expr(ctx));
      values.push(kwargs);
    }
    return values;
  }

  parsePrimary() {
    const token = this.peek();
    if (!token) throw new Error(`Unexpected end of expression: ${this.source}`);

    if (token.type === 'string') {
      this.next();
      return () => token.value;
    }
    if (token.type === 'number') {
      this.next();
      return () => token.value;
    }

    // A parenthesised expression, or a tuple literal as in `in ('a', 'b')`.
    if (this.at('op', '(')) {
      const { positional: items } = this.parseArguments();
      if (items.length === 1) return items[0];
      return (ctx) => items.map((item) => resolve(item(ctx)));
    }

    // A list literal.
    if (this.at('op', '[')) {
      this.next();
      const items = [];
      if (!this.at('op', ']')) {
        do {
          items.push(this.parseConditional());
        } while (this.eat('op', ','));
      }
      this.expect('op', ']');
      return (ctx) => items.map((item) => resolve(item(ctx)));
    }

    if (token.type === 'name') {
      if (['True', 'False', 'None', 'true', 'false', 'none'].includes(token.value)) {
        this.next();
        const literal =
          token.value === 'True' || token.value === 'true'
            ? true
            : token.value === 'False' || token.value === 'false'
              ? false
              : null;
        return () => literal;
      }
      this.next();
      const root = token.value;
      return this.parseAccessors((ctx) => (root in ctx ? ctx[root] : UNDEFINED));
    }

    throw new Error(`Unexpected token '${token.value}' in expression: ${this.source}`);
  }

  /** `.attr`, `['key']`, `[0]` and calls, chained. */
  parseAccessors(base) {
    let value = base;
    for (;;) {
      if (this.eat('op', '.')) {
        const nameToken = this.next();
        if (!nameToken || nameToken.type !== 'name') {
          throw new Error(`Expected an attribute name in: ${this.source}`);
        }
        const key = nameToken.value;
        const previous = value;
        value = (ctx) => member(previous(ctx), key);
        continue;
      }
      if (this.at('op', '[')) {
        this.next();
        const keyExpr = this.parseConditional();
        this.expect('op', ']');
        const previous = value;
        value = (ctx) => member(previous(ctx), resolve(keyExpr(ctx)));
        continue;
      }
      if (this.at('op', '(')) {
        const args = this.parseArguments();
        const previous = value;
        value = (ctx) => {
          const fn = previous(ctx);
          if (typeof fn !== 'function') return UNDEFINED;
          return fn(...ExpressionParser.evaluateArguments(args, ctx));
        };
        continue;
      }
      return value;
    }
  }
}

/** Undefined reads render as empty, as Jinja's default Undefined does. */
const resolve = (value) => (value === UNDEFINED ? undefined : value);

/** str() for the ~ operator: an undefined side contributes nothing. */
function stringify(value) {
  const v = resolve(value);
  return v === undefined || v === null ? '' : String(v);
}

/**
 * Python's dict methods, for `{% for key, spec in extras.items() %}`.
 *
 * A plain JS object has no .items()/.keys()/.values(), so they are supplied
 * here rather than rewriting the template. items() yields [key, value] pairs,
 * which the two-name form of {% for %} then unpacks.
 */
const DICT_METHODS = {
  items: (target) => Object.entries(target),
  keys: (target) => Object.keys(target),
  values: (target) => Object.values(target),
};

function member(target, key) {
  if (target === UNDEFINED || target === null || target === undefined) return UNDEFINED;

  const value = target[key];
  if (value === undefined) {
    if (
      typeof target === 'object' &&
      !Array.isArray(target) &&
      Object.hasOwn(DICT_METHODS, key)
    ) {
      return () => DICT_METHODS[key](target);
    }
    return UNDEFINED;
  }
  // Bind methods so `request.args.get('x')` keeps its receiver.
  return typeof value === 'function' ? value.bind(target) : value;
}

function normalise(value) {
  return value === UNDEFINED ? undefined : value;
}

/** Python truthiness: empty string, 0, empty list and empty dict are false. */
export function truthy(value) {
  const v = normalise(value);
  if (v === undefined || v === null || v === false) return false;
  if (v === true) return true;
  if (typeof v === 'number') return v !== 0;
  if (typeof v === 'string') return v.length > 0;
  if (Array.isArray(v)) return v.length > 0;
  if (v instanceof Safe) return v.value.length > 0;
  if (typeof v === 'object') return Object.keys(v).length > 0;
  return Boolean(v);
}

const expressionCache = new Map();

function compileExpression(source) {
  let compiled = expressionCache.get(source);
  if (!compiled) {
    compiled = new ExpressionParser(source).parse();
    expressionCache.set(source, compiled);
  }
  return compiled;
}

/* ------------------------------------------------------------------ */
/* Template parser                                                     */
/* ------------------------------------------------------------------ */

function parseTemplate(source) {
  // Jinja's keep_trailing_newline defaults to false: one trailing newline goes.
  const text = source.endsWith('\n') ? source.slice(0, -1) : source;
  const pieces = text.split(/(\{\{[\s\S]*?\}\}|\{%[\s\S]*?%\}|\{#[\s\S]*?#\})/);

  const root = { type: 'root', children: [] };
  const stack = [{ node: root, children: root.children }];
  const blocks = new Map();
  let parent = null;

  const push = (child) => stack[stack.length - 1].children.push(child);

  for (const piece of pieces) {
    if (piece === '') continue;
    // {# a comment #} renders as nothing, as in Jinja.
    if (piece.startsWith('{#')) continue;

    if (piece.startsWith('{{')) {
      push({ type: 'output', expr: compileExpression(piece.slice(2, -2)) });
      continue;
    }
    if (!piece.startsWith('{%')) {
      push({ type: 'text', value: piece });
      continue;
    }

    // Trim the tag, honouring Jinja's {%- -%} whitespace-control markers by
    // simply stripping them: the templates use them only around block tags.
    const tag = piece.slice(2, -2).replace(/^-|-$/g, '').trim();
    const [keyword, ...rest] = tag.split(/\s+/);
    const argument = rest.join(' ');

    if (keyword === 'extends') {
      parent = compileExpression(argument);
      continue;
    }

    if (keyword === 'block') {
      const node = { type: 'block', name: rest[0], children: [] };
      push(node);
      blocks.set(rest[0], node);
      stack.push({ node, children: node.children });
      continue;
    }
    if (keyword === 'endblock') {
      if (stack.pop().node.type !== 'block') throw new Error('Unmatched {% endblock %}');
      continue;
    }

    if (keyword === 'if') {
      const node = { type: 'if', branches: [{ test: compileExpression(argument), children: [] }], alternate: [] };
      push(node);
      stack.push({ node, children: node.branches[0].children });
      continue;
    }
    if (keyword === 'elif') {
      const frame = stack[stack.length - 1];
      if (frame.node.type !== 'if') throw new Error('{% elif %} outside an {% if %}');
      const branch = { test: compileExpression(argument), children: [] };
      frame.node.branches.push(branch);
      frame.children = branch.children;
      continue;
    }
    if (keyword === 'else') {
      const frame = stack[stack.length - 1];
      if (frame.node.type === 'if') {
        frame.children = frame.node.alternate;
        continue;
      }
      if (frame.node.type === 'for') {
        frame.children = frame.node.empty;
        continue;
      }
      throw new Error('{% else %} outside an {% if %} or {% for %}');
    }
    if (keyword === 'endif') {
      if (stack.pop().node.type !== 'if') throw new Error('Unmatched {% endif %}');
      continue;
    }

    if (keyword === 'for') {
      const match = /^(\w+(?:\s*,\s*\w+)?)\s+in\s+(.+)$/.exec(argument);
      if (!match) throw new Error(`Malformed {% for %}: ${tag}`);
      const node = {
        type: 'for',
        names: match[1].split(',').map((n) => n.trim()),
        iterable: compileExpression(match[2]),
        children: [],
        empty: [],
      };
      push(node);
      stack.push({ node, children: node.children });
      continue;
    }
    if (keyword === 'endfor') {
      if (stack.pop().node.type !== 'for') throw new Error('Unmatched {% endfor %}');
      continue;
    }

    if (keyword === 'set') {
      const match = /^(\w+)\s*=\s*(.+)$/.exec(argument);
      if (!match) throw new Error(`Malformed {% set %}: ${tag}`);
      push({ type: 'set', name: match[1], expr: compileExpression(match[2]) });
      continue;
    }

    if (keyword === 'include') {
      push({ type: 'include', name: compileExpression(argument.replace(/\s+(with|without)\s+context$/, '')) });
      continue;
    }

    throw new Error(`Unsupported template tag: {% ${tag} %}`);
  }

  if (stack.length !== 1) throw new Error('Unclosed {% if %}, {% for %} or {% block %}');
  return { children: root.children, blocks, parent };
}

/* ------------------------------------------------------------------ */
/* Environment                                                         */
/* ------------------------------------------------------------------ */

export class Environment {
  /** @param {Record<string,string>} templates name -> source */
  constructor(templates) {
    this.sources = templates;
    this.compiled = new Map();
  }

  get(name) {
    let template = this.compiled.get(name);
    if (!template) {
      const source = this.sources[name];
      if (source === undefined) throw new Error(`No such template: ${name}`);
      template = parseTemplate(source);
      this.compiled.set(name, template);
    }
    return template;
  }

  /**
   * Render `name` with `context`.
   *
   * Inheritance is resolved by walking up the extends chain collecting block
   * overrides, then rendering the root ancestor with the most derived block for
   * each name — which is what lets base.html hold the shell while each page
   * supplies only its title, description and content.
   */
  render(name, context = {}) {
    const overrides = new Map();
    let template = this.get(name);

    while (template.parent) {
      for (const [blockName, node] of template.blocks) {
        if (!overrides.has(blockName)) overrides.set(blockName, node);
      }
      const parentName = template.parent({ ...context });
      template = this.get(String(parentName));
    }
    for (const [blockName, node] of template.blocks) {
      if (!overrides.has(blockName)) overrides.set(blockName, node);
    }

    return this.renderNodes(template.children, { ...context }, overrides);
  }

  renderNodes(nodes, ctx, overrides) {
    let out = '';
    for (const node of nodes) {
      switch (node.type) {
        case 'text':
          out += node.value;
          break;
        case 'output':
          out += escapeHtml(resolve(node.expr(ctx)));
          break;
        case 'set':
          ctx[node.name] = resolve(node.expr(ctx));
          break;
        case 'if': {
          const branch = node.branches.find((b) => truthy(b.test(ctx)));
          out += this.renderNodes(branch ? branch.children : node.alternate, ctx, overrides);
          break;
        }
        case 'for': {
          const raw = resolve(node.iterable(ctx));
          const items = Array.isArray(raw)
            ? raw
            : raw && typeof raw === 'object'
              ? Object.keys(raw)
              : raw
                ? [...String(raw)]
                : [];
          if (items.length === 0) {
            out += this.renderNodes(node.empty, ctx, overrides);
            break;
          }
          for (const [index, item] of items.entries()) {
            // Shadow rather than mutate, so the outer binding survives the loop.
            const scope = { ...ctx };
            if (node.names.length === 1) {
              scope[node.names[0]] = item;
            } else {
              node.names.forEach((n, i) => {
                scope[n] = Array.isArray(item) ? item[i] : undefined;
              });
            }
            scope.loop = {
              index: index + 1,
              index0: index,
              first: index === 0,
              last: index === items.length - 1,
              length: items.length,
              revindex: items.length - index,
            };
            out += this.renderNodes(node.children, scope, overrides);
          }
          break;
        }
        case 'block': {
          const override = overrides.get(node.name) ?? node;
          out += this.renderNodes(override.children, ctx, overrides);
          break;
        }
        case 'include': {
          const includeName = String(resolve(node.name(ctx)));
          out += this.render(includeName, ctx);
          break;
        }
        default:
          throw new Error(`Unknown node type: ${node.type}`);
      }
    }
    return out;
  }
}
