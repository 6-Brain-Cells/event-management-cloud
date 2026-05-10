FROM nginx:1.25-alpine
COPY nginx.conf /etc/nginx/nginx.conf
COPY assets /usr/share/nginx/html/assets
COPY *.html /usr/share/nginx/html/
EXPOSE 80
