const fs = require('fs');
const path = require('path');

const gradlePath = path.join(
  __dirname,
  '..',
  'node_modules',
  '@react-native-voice',
  'voice',
  'android',
  'build.gradle'
);

if (!fs.existsSync(gradlePath)) {
  process.exit(0);
}

const source = fs.readFileSync(gradlePath, 'utf8');
const patched = source.replace(
  /implementation\s+["']com\.android\.support:appcompat-v7:\$\{supportVersion\}["']/,
  "implementation 'androidx.appcompat:appcompat:1.7.0'"
);

if (patched !== source) {
  fs.writeFileSync(gradlePath, patched);
  console.log('Patched @react-native-voice/voice Android support dependency to AndroidX.');
}
