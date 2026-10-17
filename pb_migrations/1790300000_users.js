migrate((app) => {
  const users = app.findCollectionByNameOrId("users");
  const rule = "id = @request.auth.id && @request.auth.collectionName = 'users' && @request.auth.disabled = false";
  if (!users.fields.getByName("disabled")) users.fields.add(new BoolField({ name: "disabled" }));
  const name = users.fields.getByName("name");
  if (name) {
    name.required = true;
    name.max = 200;
  } else {
    users.fields.add(new TextField({ name: "name", required: true, max: 200 }));
  }
  users.listRule = rule;
  users.viewRule = rule;
  users.createRule = null;
  users.updateRule = null;
  users.deleteRule = null;
  users.authRule = "disabled = false";
  users.authToken.duration = 604800;
  app.save(users);
}, () => {});
