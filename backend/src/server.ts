import Fastify from "fastify";
import { healthRoutes } from "./routes/health";

const app = Fastify({ logger: true });

async function main() {
  app.register(healthRoutes);
  await app.ready();

  const port = Number(process.env.PORT ?? 3000);
  await app.listen({ port, host: "0.0.0.0" });
}

main().catch((error) => {
  app.log.error(error);
  process.exit(1);
});
