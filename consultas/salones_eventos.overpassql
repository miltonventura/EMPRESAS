/*
  Salones de eventos, banquetes y convenciones
  28 distritos: AMSS y la franja costera de La Libertad.
  Pegar en https://overpass-turbo.eu -> Ejecutar -> Exportar (GeoJSON / CSV / GPX)
  Datos (c) colaboradores de OpenStreetMap, licencia ODbL
*/
[out:json][timeout:600];
rel(13.00,-90.30,14.60,-87.60)["boundary"="administrative"]["admin_level"!="2"]["admin_level"!="4"]["name"~"^(San Salvador|Ayutuxtepeque|Mejicanos|Cuscatancingo|(Ciudad )?Delgado|Apopa|Nejapa|Ilopango|San Mart[ií]n|Soyapango|Tonacatepeque|San Marcos|Panchimalco|Rosario de Mora|Santiago Texacuangos|Santo Tom[áa]s|Antiguo Cuscatl[áa]n|Huiz[úu]car|Nuevo Cuscatl[áa]n|San Jos[eé] Villa ?[Nn]ueva|Zaragoza|Chiltiup[áa]n|Jicalapa|La Libertad|Tamanique|Teotepeque|Santa Tecla|Nueva San Salvador|Comasagua)$"]->.d;
.d map_to_area ->.zona;
(
  nwr["amenity"~"^(events_venue|conference_centre|exhibition_centre)$"](area.zona);
  nwr["name"~"eventos|banquete|recepciones|convenciones|sal[oó]n social",i][!"highway"](area.zona);
);
out tags center;
