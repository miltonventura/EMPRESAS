/*
  Empresas constructoras
  28 distritos: AMSS y la franja costera de La Libertad.
  Pegar en https://overpass-turbo.eu -> Ejecutar -> Exportar (GeoJSON / CSV / GPX)
  Datos (c) colaboradores de OpenStreetMap, licencia ODbL
*/
[out:json][timeout:600];
rel(13.00,-90.30,14.60,-87.60)["boundary"="administrative"]["admin_level"!="2"]["admin_level"!="4"]["name"~"^(San Salvador|Ayutuxtepeque|Mejicanos|Cuscatancingo|(Ciudad )?Delgado|Apopa|Nejapa|Ilopango|San Mart[ií]n|Soyapango|Tonacatepeque|San Marcos|Panchimalco|Rosario de Mora|Santiago Texacuangos|Santo Tom[áa]s|Antiguo Cuscatl[áa]n|Huiz[úu]car|Nuevo Cuscatl[áa]n|San Jos[eé] Villa ?[Nn]ueva|Zaragoza|Chiltiup[áa]n|Jicalapa|La Libertad|Tamanique|Teotepeque|Santa Tecla|Nueva San Salvador|Comasagua)$"]->.d;
.d map_to_area ->.zona;
(
  nwr["office"~"^(construction_company|developer)$"](area.zona);
  nwr["craft"~"^(builder|carpenter|electrician|plumber)$"](area.zona);
  nwr["office"="architect"](area.zona);
  nwr["industrial"~"^(construction|cement|concrete)$"](area.zona);
  nwr["name"~"constructora|construcciones|urbanizadora|ingenier[ií]a|desarrollos|prefabricad",i][!"highway"][!"landuse"][!"place"](area.zona);
);
out tags center;
