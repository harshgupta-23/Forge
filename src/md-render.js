// md-render.js — Markdown + syntax highlighting for agent bubbles
// Depends on: marked (global), hljs (global) — loaded before this file

(function () {
  // Configure marked once
  marked.setOptions({
    gfm: true,       // GitHub Flavoured Markdown (tables, fenced code, strikethrough)
    breaks: true,    // single newline → <br>
    highlight: function (code, lang) {
      if (lang && hljs.getLanguage(lang)) {
        return hljs.highlight(code, { language: lang }).value;
      }
      return hljs.highlightAuto(code).value;
    }
  });

  /**
   * Convert a markdown string to an HTML string.
   * Safe to set as innerHTML on agent-controlled bubbles.
   */
  window.renderMarkdown = function (text) {
    const html = marked.parse(text);
    // Post-process: wrap every <pre><code> in a container with a copy button
    const temp = document.createElement('div');
    temp.innerHTML = html;
    temp.querySelectorAll('pre').forEach(pre => {
      const wrapper = document.createElement('div');
      wrapper.className = 'code-block-wrapper';

      // sticky bar that travels with scroll inside the code block
      const bar = document.createElement('div');
      bar.className = 'copy-btn-bar';

      const btn = document.createElement('button');
      btn.className = 'copy-btn';
      btn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none"
        stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
        </svg> Copy`;

      btn.addEventListener('click', () => {
        const code = pre.querySelector('code');
        navigator.clipboard.writeText(code ? code.textContent : pre.textContent)
          .then(() => {
            btn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="20 6 9 17 4 12"/>
              </svg> Copied!`;
            setTimeout(() => {
              btn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none"
                stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
                </svg> Copy`;
            }, 2000);
          });
      });

      bar.appendChild(btn);
      pre.parentNode.insertBefore(wrapper, pre);
      wrapper.appendChild(pre);
      wrapper.appendChild(bar);   // bar goes AFTER pre so sticky bottom works
    });
    return temp.innerHTML;
  };
})();