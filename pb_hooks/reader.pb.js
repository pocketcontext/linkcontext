routerAdd('GET', '/{$}', (e) => require(`${__hooks}/reader.js`).serve(e, 'index.html'));
routerAdd('GET', '/assets/{name}', (e) => {
  const name = e.request.pathValue('name');
  if (!/^[A-Za-z0-9_-]+\.(js|css|woff2)$/.test(name)) throw new NotFoundError();
  return require(`${__hooks}/reader.js`).serve(e, 'assets/' + name);
});
