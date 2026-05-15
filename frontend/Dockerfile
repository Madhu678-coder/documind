FROM node:20-alpine

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm install

# Copy application code
COPY . .

# Expose port
EXPOSE 5180

# Default command (can be overridden in docker-compose)
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5180"]
