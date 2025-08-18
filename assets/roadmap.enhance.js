(function () {
  const onReady = (fn) => (document.readyState !== 'loading')
    ? fn()
    : document.addEventListener('DOMContentLoaded', fn);

  onReady(() => {
    document.querySelectorAll('table.rm-table').forEach(t => {
      if (!t.parentElement.classList.contains('table-wrap')) {
        const wrap = document.createElement('div');
        wrap.className = 'table-wrap';
        t.parentElement.insertBefore(wrap, t);
        wrap.appendChild(t);
      }
    });

    const toc = document.querySelector('.rm-toc');
    if (toc) {
      let ol = toc.querySelector('ol');
      if (!ol) { ol = document.createElement('ol'); toc.appendChild(ol); }
      if (!ol.children.length) {
        const items = Array.from(document.querySelectorAll('.rm-card[id] h3'));
        items.forEach(h3 => {
          const card = h3.closest('.rm-card');
          const id = card?.id;
          const text = (h3.innerText || '').trim();
          if (id && text) {
            const li = document.createElement('li');
            const a = document.createElement('a');
            a.href = `#${id}`;
            a.textContent = text;
            li.appendChild(a);
            ol.appendChild(li);
          }
        });
      }
    }

    document.querySelectorAll('.rm-card[id] h3').forEach(h3 => {
      const card = h3.closest('.rm-card');
      const id = card?.id;
      if (!id) return;
      const a = document.createElement('a');
      a.href = `#${id}`;
      a.textContent = '#';
      a.style.marginLeft = '6px';
      a.style.textDecoration = 'none';
      a.style.color = 'var(--muted)';
      a.className = 'anchor';
      h3.appendChild(a);
    });
  });
})();
