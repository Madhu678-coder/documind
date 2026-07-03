FROM node:20-slim

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .

EXPOSE 5190

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
