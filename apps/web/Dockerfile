FROM node:22-alpine

WORKDIR /app

COPY apps/web/package.json apps/web/package-lock.json ./apps/web/
RUN npm ci --prefix apps/web

COPY apps/web ./apps/web
WORKDIR /app/apps/web

EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
