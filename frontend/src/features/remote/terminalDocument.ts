/**
 * xterm's DOM renderer creates stylesheet nodes and span style attributes.
 * Route those trusted local styles through CSSOM so the deployment can retain
 * style-src 'self'. This facade affects only this terminal, never global DOM APIs.
 */
export function terminalDocument(owner: Document) {
  if (
    !("adoptedStyleSheets" in owner) ||
    typeof CSSStyleSheet.prototype.replaceSync !== "function"
  ) {
    throw new Error("当前浏览器不支持安全终端样式，请更新浏览器后重试");
  }
  const sheets = new Set<CSSStyleSheet>();
  const facade = new Proxy(owner, {
    get(target, property) {
      if (property === "createElement") {
        return (tag: string, options?: ElementCreationOptions) => {
          if (tag.toLowerCase() !== "style") {
            const element = target.createElement(tag, options);
            if (tag.toLowerCase() === "span") {
              const setAttribute = element.setAttribute.bind(element);
              // Selection and true-color cells use style attributes in xterm.
              // Apply renderer-generated declarations through CSSOM, scoped to
              // this terminal's elements; never patch global DOM prototypes.
              element.setAttribute = (name, value) => {
                if (name.toLowerCase() === "style")
                  element.style.cssText = value;
                else setAttribute(name, value);
              };
            }
            return element;
          }
          // An inert marker preserves xterm's node lifecycle without inserting
          // inline <style> elements that the platform CSP intentionally forbids.
          const marker = target.createElement("span");
          marker.hidden = true;
          const sheet = new CSSStyleSheet();
          sheets.add(sheet);
          owner.adoptedStyleSheets = [...owner.adoptedStyleSheets, sheet];
          let css = "";
          Object.defineProperty(marker, "textContent", {
            configurable: true,
            get: () => css,
            set: (value: string | null) => {
              css = value || "";
              sheet.replaceSync(css);
            },
          });
          return marker;
        };
      }
      const value = Reflect.get(target, property, target);
      return typeof value === "function" ? value.bind(target) : value;
    },
  });
  return {
    document: facade,
    dispose: () => {
      owner.adoptedStyleSheets = owner.adoptedStyleSheets.filter(
        (sheet) => !sheets.has(sheet),
      );
      sheets.clear();
    },
  };
}

/** xterm 5.5.0 passes the global document to its DOM row factory even when
 * documentOverride is set. Bind that factory to the same terminal-local facade.
 * Keep this adapter checked when upgrading xterm; never patch the global DOM.
 */
export function bindTerminalRowDocument(terminal: unknown, document: Document) {
  const rowFactory = (
    terminal as {
      _core?: {
        _renderService?: {
          _renderer?: {
            value?: {
              _rowFactory?: { _document: Document };
            };
          };
        };
      };
    }
  )._core?._renderService?._renderer?.value?._rowFactory;
  if (!rowFactory) throw new Error("当前终端版本不支持安全的文字样式适配");
  rowFactory._document = document;
}
