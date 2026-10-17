/// <reference path="../pb_data/types.d.ts" />
routerAdd("GET", "/up", (e) => require(`${__hooks}/deploy.js`).up(e), $apis.skipSuccessActivityLog());

onBootstrap((e) => {
  e.next();
  if (e.app.store().get("pocketcontextMaintenanceReadOnly") === true) {
    require(`${__hooks}/storage.js`).configure(e.app, true);
    return;
  }
  require(`${__hooks}/deploy.js`).settings(e.app);
  require(`${__hooks}/deploy.js`).googleOAuth(e.app);
  require(`${__hooks}/deploy.js`).localBootstrap(e.app);
});
