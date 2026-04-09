# Further Frontend

这个目录现在作为项目的主前端。

## 本地开发

1. 安装依赖：`npm install`
2. 启动开发服务器：`npm run dev`
3. 访问：`http://localhost:5173`

## 生产构建

1. 执行：`npm run build`
2. 构建产物输出到 `dist/`
3. 启动 `python -m agentsociety2.backend.run` 后，使用 `http://localhost:8001` 提供后端接口
