/// <reference path="../pb_data/types.d.ts" />
onRecordCreateExecute((e) => require(`${__hooks}/user_directory.js`).sync(e, false), "users");
onRecordUpdateExecute((e) => require(`${__hooks}/user_directory.js`).sync(e, false), "users");
onRecordDeleteExecute((e) => require(`${__hooks}/user_directory.js`).sync(e, true), "users");
