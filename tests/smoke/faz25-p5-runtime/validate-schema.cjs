'use strict';

const fs = require('node:fs');
const Ajv = require('ajv');

const [schemaPath, dataPath] = process.argv.slice(2);
if (!schemaPath || !dataPath) {
  process.stderr.write('usage: validate-schema.cjs <schema.json> <data.json>\n');
  process.exit(2);
}

const schema = JSON.parse(fs.readFileSync(schemaPath, 'utf8'));
const data = JSON.parse(fs.readFileSync(dataPath, 'utf8'));
const ajv = new Ajv({ strict: true, allErrors: true });
const validate = ajv.compile(schema);

if (!validate(data)) {
  process.stderr.write(`${JSON.stringify(validate.errors, null, 2)}\n`);
  process.exit(1);
}
