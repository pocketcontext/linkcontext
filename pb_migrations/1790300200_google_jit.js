migrate((app) => {
  const users = app.findCollectionByNameOrId("users");
  users.createRule = "@request.context = 'oauth2'";
  app.save(users);
}, (app) => {
  const users = app.findCollectionByNameOrId("users");
  users.createRule = null;
  app.save(users);
});
