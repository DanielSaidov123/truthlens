FROM node:22-alpine

WORKDIR /app

COPY package.json package-lock.json ./
COPY prisma ./prisma

RUN npm ci && npx prisma generate

COPY tsconfig.json ./
COPY src ./src

EXPOSE 3000

CMD ["npx", "tsx", "src/server.ts"]
