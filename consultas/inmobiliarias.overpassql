/*
  Empresas inmobiliarias y constructoras - zona del volcan de San Salvador (El Salvador)
  Pegar en https://overpass-turbo.eu -> Ejecutar -> Exportar (GeoJSON / CSV / GPX)
  Centro: crater El Boqueron 13.7342, -89.2864 | Radio: 15 km
  Datos (c) colaboradores de OpenStreetMap, licencia ODbL
*/
[out:json][timeout:180];
(
  nwr["office"~"^(estate_agent|property_management|developer|construction_company)$"](around:15000,13.7342,-89.2864);
  nwr["shop"="estate_agent"](around:15000,13.7342,-89.2864);
  nwr["craft"="builder"](around:15000,13.7342,-89.2864);
  nwr["office"="architect"](around:15000,13.7342,-89.2864);
  nwr["name"~"inmobiliari|bienes ra|constructora|urbanizadora|desarrollos",i][!"highway"][!"landuse"][!"place"](around:15000,13.7342,-89.2864);
);
out tags center;
