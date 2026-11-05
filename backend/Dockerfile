FROM node:22-alpine

WORKDIR /app

COPY package.json tsconfig.json ./
COPY src ./src

RUN npm install

EXPOSE 3000

CMD ["npx", "tsx", "src/server.ts"]
