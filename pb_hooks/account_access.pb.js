/// <reference path="../pb_data/types.d.ts" />
routerUse(new Middleware((e) => require(`${__hooks}/account_access.js`).request(e), -1019));
onRecordAuthRequest((e) => require(`${__hooks}/account_access.js`).authenticate(e), "users");
onRecordUpdate((e) => require(`${__hooks}/account_access.js`).update(e), "users");
onRecordDelete((e) => require(`${__hooks}/account_access.js`).remove(e), "users");
onRealtimeMessageSend((e) => require(`${__hooks}/account_access.js`).realtime(e));
