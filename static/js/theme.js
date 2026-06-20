/* Nexora — theme toggle (vanilla JS, shared by all three role shells).
   The no-flash <head> snippet has already set data-theme before paint; this
   only handles toggling + persistence (localStorage now, profile server-side). */
(function () {
  var KEY = 'nx-theme';

  function current() {
    return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
  }
  function apply(theme) {
    document.documentElement.setAttribute('data-theme', theme);
  }
  function getCookie(name) {
    var m = document.cookie.match('(^|;)\\s*' + name + '\\s*=\\s*([^;]+)');
    return m ? m.pop() : '';
  }
  function syncButtons(theme) {
    document.querySelectorAll('[data-theme-toggle]').forEach(function (btn) {
      btn.setAttribute('aria-label', theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme');
      var icon = btn.querySelector('[data-theme-icon]');
      if (icon) icon.textContent = theme === 'dark' ? '☀' : '☾'; // ☀ / ☾
    });
  }

  function toggle(btn) {
    var next = current() === 'dark' ? 'light' : 'dark';
    apply(next);
    syncButtons(next);
    try { localStorage.setItem(KEY, next); } catch (e) {}
    var url = btn.getAttribute('data-theme-url');
    if (url) {
      // Best-effort durable persistence; UI already updated regardless.
      fetch(url, {
        method: 'POST',
        headers: {
          'X-CSRFToken': getCookie('csrftoken'),
          'Content-Type': 'application/x-www-form-urlencoded'
        },
        body: 'theme=' + next
      }).catch(function () {});
    }
  }

  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-theme-toggle]');
    if (btn) { e.preventDefault(); toggle(btn); }
  });

  syncButtons(current());
})();
