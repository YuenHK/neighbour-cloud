// Fetch the current app shell before Vue Router starts, without clearing user data.
(() => {
  if (location.pathname === '/ui/estate-resident-entry.html')
    history.replaceState(history.state, '', `/${location.search}${location.hash}`)
})()
