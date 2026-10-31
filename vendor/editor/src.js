// Source of static/vendor/editor.js. Exposes window.HLEditor:
//   mount(el, text, { words, onChange }) -> { get(), set(text), destroy() }
//   highlight(text) -> HTML with <span class="tok-..."> around C++ tokens (text escaped)
import { EditorState } from "@codemirror/state";
import { EditorView, keymap, lineNumbers, highlightActiveLine, drawSelection } from "@codemirror/view";
import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import { bracketMatching, syntaxHighlighting, HighlightStyle, indentOnInput } from "@codemirror/language";
import { autocompletion, closeBrackets, completeFromList, completionKeymap } from "@codemirror/autocomplete";
import { cpp, cppLanguage } from "@codemirror/lang-cpp";
import { tags as t, highlightTree, classHighlighter } from "@lezer/highlight";

// Kid-sized, high-contrast colours on the app's dark code panel (matches .tok-* in index.html).
const style = HighlightStyle.define([
  { tag: t.keyword, class: "tok-keyword" },
  { tag: [t.typeName, t.standard(t.typeName)], class: "tok-type" },
  { tag: [t.number, t.bool], class: "tok-number" },
  { tag: t.string, class: "tok-string" },
  { tag: [t.comment, t.lineComment, t.blockComment], class: "tok-comment" },
  { tag: [t.function(t.variableName), t.function(t.propertyName)], class: "tok-function" },
  { tag: t.processingInstruction, class: "tok-macro" },
]);

const ARDUINO = ["setup", "loop", "pinMode", "digitalWrite", "digitalRead", "analogRead", "analogWrite",
  "delay", "delayMicroseconds", "millis", "micros", "map", "constrain", "min", "max", "abs", "random",
  "Serial", "Serial.begin", "Serial.print", "Serial.println", "HIGH", "LOW", "INPUT", "OUTPUT",
  "INPUT_PULLUP", "true", "false", "int", "long", "float", "bool", "byte", "char", "void", "const",
  "unsigned", "if", "else", "for", "while", "switch", "case", "break", "return"];

function wordsIn(text) {
  const seen = new Set();
  for (const m of text.matchAll(/\b[A-Za-z_][A-Za-z0-9_]{2,}\b/g)) seen.add(m[0]);
  return seen;
}

export function mount(el, text, opts = {}) {
  const words = new Set([...ARDUINO, ...(opts.words || []), ...wordsIn(text)]);
  const source = completeFromList([...words].sort().map((label) => ({ label, type: /^[A-Z_]+$/.test(label) ? "constant" : "variable" })));
  const state = EditorState.create({
    doc: text,
    extensions: [
      lineNumbers(), highlightActiveLine(), drawSelection(), history(), bracketMatching(), closeBrackets(),
      indentOnInput(), cpp(), syntaxHighlighting(style),
      autocompletion({ override: [source], activateOnTyping: true, icons: false }),
      keymap.of([...closeBracketsKeymapSafe(), ...defaultKeymap, ...historyKeymap, ...completionKeymap, indentWithTab]),
      EditorView.lineWrapping,
      EditorView.updateListener.of((u) => { if (u.docChanged && opts.onChange) opts.onChange(u.state.doc.toString()); }),
    ],
  });
  const view = new EditorView({ state, parent: el });
  return {
    get: () => view.state.doc.toString(),
    set: (t) => view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: t } }),
    destroy: () => view.destroy(),
    view,
  };
}

function closeBracketsKeymapSafe() { return []; } // closeBrackets() installs its own input handler

const esc = (s) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export function highlight(text) {
  return highlightLines(text).join("\n");
}

// One HTML string per source line; a token spanning lines (block comments) is split so
// every line's spans are self-contained. Whole-text parse, so comment state is right.
export function highlightLines(text) {
  const tree = cppLanguage.parser.parse(text);
  const lines = [""];
  let pos = 0;
  const emit = (s, cls) => {
    const parts = s.split("\n");
    parts.forEach((part, i) => {
      if (i) lines.push("");
      if (part) lines[lines.length - 1] += cls ? `<span class="${cls}">${esc(part)}</span>` : esc(part);
    });
  };
  highlightTree(tree, classHighlighter, (from, to, classes) => {
    if (from > pos) emit(text.slice(pos, from), "");
    emit(text.slice(from, to), classes);
    pos = to;
  });
  emit(text.slice(pos), "");
  return lines;
}
