// audience: internal
// server-starter
// 启动 NeteaseCloudMusicApi，跳过 generateConfig() 避免重复注册匿名设备。

const fs = require('fs')
const path = require('path')
const tmpPath = require('os').tmpdir()

// 确保 anonymous_token 文件存在，维持同一匿名会话
const tokenFile = path.resolve(tmpPath, 'anonymous_token')
if (!fs.existsSync(tokenFile)) {
  fs.writeFileSync(tokenFile, '', 'utf-8')
}

const { generateRandomChineseIP } = require('./node_modules/NeteaseCloudMusicApi/util/index')
global.cnIp = generateRandomChineseIP()

const { serveNcmApi } = require('./node_modules/NeteaseCloudMusicApi/server')
serveNcmApi({ checkVersion: false })
