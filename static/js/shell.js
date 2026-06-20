/* Nexora app shell — shared sidebar behaviour for both roles.
   - Mobile (<=860px): off-canvas drawer toggled by the topbar hamburger and
     closed by the backdrop overlay.
   - Desktop (>=861px): icon-rail collapse toggled by the footer chevron;
     state persisted in localStorage so it survives reloads.
   Elements (rendered by templates/_shell/sidebar.html + the role base):
     #nx-sidebar  #nx-overlay  #nx-hamburger  #nx-railtoggle               */
(function () {
  var RAIL_KEY = 'nx-side-rail';
  var sidebar = document.getElementById('nx-sidebar');
  if (!sidebar) return;
  var overlay = document.getElementById('nx-overlay');
  var hamburger = document.getElementById('nx-hamburger');
  var railToggle = document.getElementById('nx-railtoggle');

  // Restore persisted desktop rail state (CSS ignores .is-collapsed on mobile).
  try { if (localStorage.getItem(RAIL_KEY) === '1') sidebar.classList.add('is-collapsed'); } catch (e) {}

  function openDrawer() {
    sidebar.classList.add('is-open');
    if (overlay) overlay.classList.add('is-open');
  }
  function closeDrawer() {
    sidebar.classList.remove('is-open');
    if (overlay) overlay.classList.remove('is-open');
  }
  function toggleRail() {
    sidebar.classList.toggle('is-collapsed');
    try { localStorage.setItem(RAIL_KEY, sidebar.classList.contains('is-collapsed') ? '1' : '0'); } catch (e) {}
  }

  if (hamburger) hamburger.addEventListener('click', openDrawer);
  if (overlay) overlay.addEventListener('click', closeDrawer);
  if (railToggle) railToggle.addEventListener('click', toggleRail);
})();
