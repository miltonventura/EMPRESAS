/*
  Residenciales, colonias, condominios y apartamentos - zona del volcan de San Salvador (El Salvador)
  Pegar en https://overpass-turbo.eu -> Ejecutar -> Exportar (GeoJSON / CSV / GPX)
  Centro: crater El Boqueron 13.7342, -89.2864 | Radio: 15 km
  Datos (c) colaboradores de OpenStreetMap, licencia ODbL
*/
[out:json][timeout:180];
(
  nwr["landuse"="residential"]["name"](around:15000,13.7342,-89.2864);
  nwr["place"~"^(neighbourhood|suburb|quarter|city_block)$"]["name"](around:15000,13.7342,-89.2864);
  nwr["building"~"^(apartments|residential)$"]["name"](around:15000,13.7342,-89.2864);
  nwr["residential"~"^(apartments|urban|gated)$"]["name"](around:15000,13.7342,-89.2864);
  nwr["name"~"residencial|condominio|apartament|urbanizaci|lotificaci|reparto |colonia ",i][!"highway"](around:15000,13.7342,-89.2864);
);
out tags center;
