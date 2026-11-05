try {
  var pref = localStorage.getItem('pigeon.theme') || 'dark'
  try {
    pref = JSON.parse(pref)
  } catch (e) {}
  var dark = pref === 'dark' || (pref === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)
  if (dark) document.documentElement.classList.add('dark')
  document.documentElement.style.colorScheme = dark ? 'dark' : 'light'
  var meta = document.querySelector('meta[name="theme-color"]')
  if (meta) meta.setAttribute('content', dark ? '#212121' : '#ffffff')
} catch (e) {}
