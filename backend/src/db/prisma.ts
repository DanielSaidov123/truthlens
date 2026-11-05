import { PrismaClient } from "@prisma/client";

/**
 * Single Prisma client for the backend process.
 * The worker uses psycopg directly; Prisma is backend-only.
 */
export const prisma = new PrismaClient();
