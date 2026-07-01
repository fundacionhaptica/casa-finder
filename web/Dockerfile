# casa-finder — web (paso 4)
# nginx sirviendo la web estatica Alpine.js + proxy a la API.
FROM nginx:1.27-alpine

COPY web/nginx.conf /etc/nginx/conf.d/default.conf
COPY web/dist/ /usr/share/nginx/html/

EXPOSE 80