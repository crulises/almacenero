// Panel de admin de Almacenero. Habla SOLO con el backend (/v1/admin).
// Alpine.js (CDN) + fetch; sin build. Todo el estado vive en `panel()`.

const API = window.API_URL;
const CLAVE = "almacenero_admin_sesion";

const SECCIONES = {
  locales: { ruta: "/admin/locales", filtros: { verificado: "", fuente: "", q: "", sin_precios: false, orden: "alta" } },
  usuarios: { ruta: "/admin/usuarios", filtros: { tipo: "", rol: "", estado: "", escalon: "", q: "", orden: "alta" } },
  precios: { ruta: "/admin/precios", filtros: { local_id: "", ean: "", user_id: "", desde: "", hasta: "" } },
  productos: { ruta: "/admin/productos", filtros: { q: "", origen: "", con_conflictos: false, estado: "", motivo: "", orden: "nombre" } },
  conflictos: { ruta: "/admin/conflictos", filtros: { estado: "pendiente" } },
  sugerencias: { ruta: "/admin/sugerencias", filtros: { estado: "pendiente", q: "" } },
  invitaciones: { ruta: "/admin/invitaciones", filtros: { estado: "", q: "" } },
  etl: { ruta: "/admin/etl/ejecuciones", filtros: { etl: "", estado: "" } },
  auditoria: { ruta: "/admin/auditoria", filtros: { entidad: "" } },
};

const TITULOS = {
  dashboard: "Inicio", locales: "Locales", usuarios: "Usuarios", invitaciones: "Invitaciones", precios: "Precios", catalogo: "Catálogo",
  etl: "ETL", config: "Configuración", auditoria: "Auditoría", ayuda: "Ayuda",
};

function leerSesion() {
  try { return JSON.parse(localStorage.getItem(CLAVE)); } catch { return null; }
}

function panel() {
  const sec = {};
  for (const [n, d] of Object.entries(SECCIONES)) {
    sec[n] = { items: [], total: 0, offset: 0, limit: 50, f: { ...d.filtros }, sel: {}, cargando: false };
  }
  return {
    API, TITULOS, sec,
    sesion: leerSesion(),
    vista: "dashboard",
    subcatalogo: "productos",  // dentro de Catálogo: productos | sugerencias | alta | conflictos
    login: { email: "", password: "", error: "", enviando: false },
    config: [],
    reglas: [],  // mensajes de error editables (docs/04 §10-E)
    estandares: [],  // ayuda: estándares de carga (Doc 8)
    calidad: null,  // tablero de calidad del catálogo (Doc 7)
    pendientes: 0,  // conflictos + sugerencias sin resolver (globito de Catálogo)
    pendientesConflictos: 0,
    pendientesSugerencias: 0,
    // Alta / corrección simple por EAN (Doc 7 §5.1): buscar → formulario corto.
    alta: { ean: "", buscado: false, d: null, b: {}, marcas: [], enviando: false },
    destino: "",
    // Generador de PINs de invitación (un solo uso). `nuevos` = los recién creados.
    pines: { cantidad: 1, nota: "", n: 24, unidad: "h", sinVencimiento: false, nuevos: [], enviando: false },
    // ETL (docs/04 §10-A): definiciones (el formulario se arma con ellas), historial y detalle.
    etlDefs: [],
    etlClave: "",
    etlForm: {},
    etlArchivos: {},  // parámetro -> {id, nombre, tamano} ya subido
    etlSubiendo: false,
    etlEnviando: false,
    etlDetalle: null,
    _etlTimer: null,
    ficha: null,
    edicion: null,  // conflicto que se está editando a mano ({c, base, f})
    toast: null,
    _t: null,

    init() { if (this.sesion) this.cambiarVista("dashboard"); },

    // ------------------------------------------------------------- red
    async api(path, { method = "GET", body, crudo } = {}, reintento = true) {
      let r;
      try {
        r = await fetch(API + "/v1" + path, {
          method,
          headers: {
            Authorization: "Bearer " + this.sesion.access_token,
            ...(crudo !== undefined ? { "Content-Type": "application/octet-stream" }
              : body !== undefined ? { "Content-Type": "application/json" } : {}),
          },
          body: crudo !== undefined ? crudo : body !== undefined ? JSON.stringify(body) : undefined,
        });
      } catch {
        // El navegador no distingue «sin red» de «el backend se cayó»: se lo decimos nosotros.
        throw new Error(`No hay respuesta del backend (${API}). Puede estar caído o sin red; si recién hiciste una acción, revisá los logs del backend antes de reintentar.`);
      }
      if (r.status === 401 && reintento && (await this.renovar())) return this.api(path, { method, body, crudo }, false);
      if (r.status === 401) { this.salir(); throw new Error("La sesión venció: entrá de nuevo"); }
      if (r.status === 204) return null;
      const datos = await r.json().catch(() => ({}));
      if (!r.ok) {
        const err = new Error(this.mensaje(datos.detail) || `Error ${r.status}`);
        err.status = r.status; err.detalle = datos.detail;
        throw err;
      }
      return datos;
    },
    mensaje(d) {
      if (!d) return "";
      if (typeof d === "string") return d;
      if (Array.isArray(d)) return d.map((e) => `${(e.loc || []).slice(1).join(".")}: ${e.msg}`).join("; ");
      if (!d.mensaje) return JSON.stringify(d);
      // Regla de negocio (backend/app/services/reglas.py): qué pasó, por qué y qué hacer.
      let t = d.mensaje;
      if (d.campos && d.campos.length) t += " (" + d.campos.map((c) => `${c.campo} ${c.problema}`).join("; ") + ")";
      if (d.como_resolver) t += " → " + d.como_resolver;
      if (d.codigo) t += ` [${d.codigo}${d.referencia ? " · ref " + d.referencia : ""}]`;
      return t;
    },
    async renovar() {
      try {
        const r = await fetch(API + "/v1/auth/refresh", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: this.sesion.refresh_token }),
        });
        if (!r.ok) return false;
        const s = await r.json();
        this.guardarSesion({ ...this.sesion, access_token: s.access_token, refresh_token: s.refresh_token });
        return true;
      } catch { return false; }
    },
    guardarSesion(s) {
      this.sesion = s;
      try { localStorage.setItem(CLAVE, JSON.stringify(s)); } catch {}
    },
    avisar(texto, mal = false) {
      clearTimeout(this._t);
      this.toast = { texto, mal };
      this._t = setTimeout(() => (this.toast = null), mal ? 7000 : 3000);
    },
    async intentar(fn) {
      try { return await fn(); } catch (e) { this.avisar(e.message, true); }
    },

    // ----------------------------------------------------------- sesión
    async entrar() {
      this.login.error = ""; this.login.enviando = true;
      try {
        const r = await fetch(API + "/v1/admin/login", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: this.login.email, password: this.login.password }),
        });
        const d = await r.json().catch(() => ({}));
        if (r.status === 401) throw new Error("Email o contraseña incorrectos");
        if (r.status === 403) throw new Error("Esa cuenta no es de admin");
        if (!r.ok) throw new Error(this.mensaje(d.detail) || `Error ${r.status}`);
        this.guardarSesion(d);
        this.login.password = "";
        this.cambiarVista("dashboard");
      } catch (e) {
        this.login.error = e instanceof TypeError ? "No puedo conectar con el backend (" + API + ")" : e.message;
      } finally { this.login.enviando = false; }
    },
    salir() {
      this.sesion = null;
      try { localStorage.removeItem(CLAVE); } catch {}
    },

    // ------------------------------------------------------- navegación
    // Sección cuyos datos se están viendo (Catálogo agrupa productos y conflictos).
    get actual() { return this.vista === "catalogo" ? this.subcatalogo : this.vista; },
    cambiarVista(v) {
      this.vista = v;
      clearInterval(this._etlTimer);
      if (v === "etl") { this.iniciarEtl(); return; }
      if (v === "dashboard") { this.cargarDashboard(); return; }
      if (v === "config") { this.cargarConfig(); this.cargarReglas(); }
      else if (v === "ayuda") this.cargarAyuda();
      else if (!(v === "catalogo" && this.subcatalogo === "alta")) this.cargar(v === "catalogo" ? this.subcatalogo : v);
      if (v === "catalogo") { this.contarPendientes(); this.cargarTablero(); }
    },
    async cargarAyuda() {
      if (this.estandares.length) return;
      await this.intentar(async () => { this.estandares = await this.api("/ayuda/estandares"); });
    },
    async contarPendientes() {
      try { this.pendientesConflictos = (await this.api("/admin/conflictos?estado=pendiente&limit=1")).total; } catch {}
      try { this.pendientesSugerencias = (await this.api("/admin/sugerencias?estado=pendiente&limit=1")).total; } catch {}
      this.pendientes = this.pendientesConflictos + this.pendientesSugerencias;
    },
    async cargarTablero() {
      try { this.calidad = await this.api("/admin/catalogo/calidad"); } catch {}
    },
    // Un clic en el tablero filtra el listado: «dudosos primero» y a revisar.
    verCalidad({ estado = "", motivo = "" } = {}) {
      Object.assign(this.sec.productos.f, { estado, motivo, orden: estado || motivo ? "calidad" : "nombre" });
      this.irCatalogo("productos");
    },
    irCatalogo(sub) { this.subcatalogo = sub; this.cambiarVista("catalogo"); },
    ir(vista, filtros) {
      Object.assign(this.sec[vista].f, filtros);
      this.sec[vista].offset = 0;
      this.cambiarVista(vista);
    },

    // --------------------------------------------------------- dashboard
    // Docs/04 §11. El backend agrupa en la zona del panel y devuelve instantes UTC (con Z); acá
    // solo se formatea con Intl en esa misma zona. Los períodos («hoy», «mes»…) arrancan en la
    // medianoche de esa zona, no en la del navegador.
    dash: {
      periodo: "7d", granularidad: "dia", metrica: "precios", rankTipo: "precios", via: "",
      desde: "", hasta: "",  // solo para «rango» (fechas AAAA-MM-DD en la zona del panel)
      zona: "", resumen: null, serie: null, ranking: [], estrellas: [], cargando: false,
    },
    // Diferencia (min) entre la hora de pared de `zona` y UTC en el instante `t`.
    _offsetMin(zona, t) {
      const p = Object.fromEntries(new Intl.DateTimeFormat("en-US", {
        timeZone: zona, hourCycle: "h23", year: "numeric", month: "numeric", day: "numeric",
        hour: "numeric", minute: "numeric", second: "numeric",
      }).formatToParts(t).map((x) => [x.type, +x.value]));
      return (Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second) - Math.floor(t.getTime() / 1000) * 1000) / 60000;
    },
    // Instante UTC de la medianoche, en `zona`, del día local y/m/d (d puede salirse del mes).
    _medianoche(zona, y, m, d) {
      const nominal = new Date(Date.UTC(y, m, d));
      return new Date(nominal.getTime() - this._offsetMin(zona, nominal) * 60000);
    },
    _hoyLocal(zona) {
      const p = Object.fromEntries(new Intl.DateTimeFormat("en-US", { timeZone: zona, year: "numeric", month: "numeric", day: "numeric" })
        .formatToParts(new Date()).map((x) => [x.type, +x.value]));
      return { y: p.year, m: p.month - 1, d: p.day };
    },
    rangoDashboard() {
      const z = this.dash.zona, { y, m, d } = this._hoyLocal(z), ahora = new Date();
      const k = this.dash.periodo;
      if (k === "hoy") return [this._medianoche(z, y, m, d), ahora];
      if (k === "7d") return [this._medianoche(z, y, m, d - 6), ahora];
      if (k === "30d") return [this._medianoche(z, y, m, d - 29), ahora];
      if (k === "mes") return [this._medianoche(z, y, m, 1), ahora];
      const f = (t) => { const [a, b, c] = t.split("-").map(Number); return [a, b - 1, c]; };
      if (!this.dash.desde || !this.dash.hasta) return null;
      const [y1, m1, d1] = f(this.dash.desde), [y2, m2, d2] = f(this.dash.hasta);
      return [this._medianoche(z, y1, m1, d1), this._medianoche(z, y2, m2, d2 + 1)];
    },
    elegirPeriodo(k) {
      this.dash.periodo = k;
      this.dash.granularidad = k === "hoy" ? "hora" : "dia";
      this.cargarDashboard();
    },
    async cargarDashboard() {
      const D = this.dash;
      D.cargando = true;
      await this.intentar(async () => {
        if (!D.zona) D.zona = (await this.api("/admin/dashboard/resumen")).zona;
        const r = this.rangoDashboard();
        if (!r) return;
        const q = new URLSearchParams({ desde: r[0].toISOString(), hasta: r[1].toISOString(), zona: D.zona });
        const qs = new URLSearchParams({ desde: q.get("desde"), hasta: q.get("hasta") });
        const [resumen, serie, ranking, estrellas] = await Promise.all([
          this.api(`/admin/dashboard/resumen?${q}`),
          this.api(`/admin/dashboard/series?${new URLSearchParams({ metrica: D.metrica, granularidad: D.granularidad, desde: q.get("desde"), hasta: q.get("hasta"), zona: D.zona })}`),
          this.api(`/admin/dashboard/rankings?${new URLSearchParams({ tipo: D.rankTipo, desde: q.get("desde"), hasta: q.get("hasta") })}`),
          this.api(`/admin/dashboard/estrellas?${new URLSearchParams({ ...Object.fromEntries(qs), ...(D.via ? { via: D.via } : {}) })}`),
        ]);
        Object.assign(D, { resumen, serie, ranking, estrellas });
      });
      D.cargando = false;
    },
    // «01/03 14:00» en la zona del panel (el backend manda UTC; acá se muestra, no se calcula).
    etiquetaBarra(iso) {
      const o = { timeZone: this.dash.zona };
      const g = this.dash.serie?.granularidad;
      if (g === "hora") return new Intl.DateTimeFormat("es-AR", { ...o, day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(new Date(iso));
      if (g === "mes") return new Intl.DateTimeFormat("es-AR", { ...o, month: "short", year: "numeric" }).format(new Date(iso));
      return new Intl.DateTimeFormat("es-AR", { ...o, day: "2-digit", month: "2-digit" }).format(new Date(iso));
    },
    maximoSerie() { return Math.max(1, ...(this.dash.serie?.puntos || []).map((p) => p.valor)); },

    // ---------------------------------------------------------- listados
    query(nombre, extra = {}) {
      const s = this.sec[nombre];
      const p = new URLSearchParams();
      for (const [k, v] of Object.entries(s.f)) if (v !== "" && v !== false && v != null) p.set(k, v);
      p.set("limit", s.limit); p.set("offset", s.offset);
      for (const [k, v] of Object.entries(extra)) p.set(k, v);
      return p.toString();
    },
    async cargar(nombre, reiniciar = false) {
      const s = this.sec[nombre];
      if (!s) return;  // «alta» no es un listado
      if (reiniciar) s.offset = 0;
      s.cargando = true;
      await this.intentar(async () => {
        const d = await this.api(`${SECCIONES[nombre].ruta}?${this.query(nombre)}`);
        s.items = d.items; s.total = d.total; s.sel = {};
      });
      s.cargando = false;
    },
    pagina(nombre, delta) {
      const s = this.sec[nombre];
      s.offset = Math.max(0, s.offset + delta * s.limit);
      this.cargar(nombre);
    },
    rango(nombre) {
      const s = this.sec[nombre];
      return s.total ? `${s.offset + 1}–${Math.min(s.offset + s.limit, s.total)} de ${s.total}` : "sin resultados";
    },
    elegidos(nombre) { return Object.keys(this.sec[nombre].sel).filter((k) => this.sec[nombre].sel[k]); },
    marcarTodos(nombre, v) { for (const i of this.sec[nombre].items) this.sec[nombre].sel[i.id] = v; },
    quitar(nombre, ids) {
      const s = this.sec[nombre]; const fuera = new Set(ids);
      s.items = s.items.filter((i) => !fuera.has(i.id)); s.total -= fuera.size; s.sel = {};
    },

    // -------------------------------------------------- edición en línea
    async parchar(ruta, fila, cuerpo) {
      await this.intentar(async () => {
        try {
          const nuevo = await this.api(ruta, { method: "PATCH", body: cuerpo });
          Object.assign(fila, nuevo);
          this.avisar("Guardado");
        } catch (e) { await this.cargar(this.actual); throw e; }
      });
    },
    local(l, campo, valor) { return this.parchar(`/admin/locales/${l.id}`, l, { [campo]: valor.trim() || null }); },
    ubicacion(l, lat, lng) {
      if (isNaN(lat) || isNaN(lng)) return this.avisar("Ubicación inválida", true);
      return this.parchar(`/admin/locales/${l.id}`, l, { lat, lng });
    },
    alias(u, valor) { return this.parchar(`/admin/usuarios/${u.id}`, u, { alias: valor }); },
    monto(p, valor) { return this.parchar(`/admin/precios/${p.id}`, p, { precio: valor }); },
    producto(p, campos) { return this.parchar(`/admin/productos/${p.id}`, p, campos).then(() => this.cargarTablero()); },

    // -------------------------------------------------------- masivas
    async validarLocales(ids) {
      await this.intentar(async () => {
        const r = await this.api("/admin/locales/validar", { method: "POST", body: { ids } });
        this.avisar(`${r.afectados} local(es) validados`);
        await this.cargar("locales");
      });
    },
    async borrarLocales(ids) {
      if (!confirm(`¿Borrar ${ids.length} local(es)? Los que tengan precios se omiten.`)) return;
      await this.intentar(async () => {
        const r = await this.api("/admin/locales/borrar", { method: "POST", body: { ids } });
        this.avisar(`${r.afectados} borrado(s)` + (r.omitidos.length ? `, ${r.omitidos.length} omitido(s): ${r.motivo}` : ""), r.omitidos.length > 0);
        await this.cargar("locales");
      });
    },
    async fusionar(ids) {
      const origen = ids.filter((i) => i !== this.destino);
      if (!this.destino || !origen.length) return this.avisar("Elegí el local destino entre los seleccionados", true);
      if (!confirm(`Fusionar ${origen.length} local(es) en el elegido? Sus precios se mueven y ellos se borran.`)) return;
      await this.intentar(async () => {
        await this.api("/admin/locales/fusionar", { method: "POST", body: { destino_id: this.destino, origen_ids: origen } });
        this.avisar("Fusionados");
        this.destino = "";
        await this.cargar("locales");
      });
    },
    async borrarPrecios(ids) {
      if (!confirm(`¿Borrar ${ids.length} precio(s)? Queda el rastro en Auditoría.`)) return;
      await this.intentar(async () => {
        const r = await this.api("/admin/precios/borrar", { method: "POST", body: { ids } });
        this.avisar(`${r.afectados} precio(s) borrados`);
        await this.cargar("precios");
      });
    },
    async resolver(c, elegido) {
      await this.intentar(async () => {
        await this.api(`/admin/conflictos/${c.id}/resolver`, { method: "POST", body: { elegido } });
        this.avisar("Resuelto");
        this.quitar("conflictos", [c.id]);
        this.contarPendientes();
      });
    },

    // «Editar y resolver»: ni A ni B están bien; se corrigen los datos a mano y se cierra el conflicto.
    async editarConflicto(c) {
      await this.intentar(async () => {
        let p = {};
        try { p = await this.api(`/admin/productos/por-ean/${c.ean}`); } catch {}
        const f = {
          nombre: p.nombre || c.producto_nombre || "", marca: p.marca || "",
          tamano_valor: p.tamano_valor ?? "", tamano_unidad: p.tamano_unidad || "",
          pack_cantidad: p.pack_cantidad ?? "", presentacion: p.presentacion || "", motivo: "",
        };
        this.edicion = { c, base: { ...f }, f };
      });
    },
    async guardarEdicion() {
      const { c, base, f } = this.edicion;
      const cambia = (k) => String(f[k]) !== String(base[k]);
      const vacio = (v) => (v === "" || v === null ? null : v);
      const cuerpo = {};
      // el campo en disputa viaja siempre: «confirmar tal cual» también cierra el conflicto
      for (const k of ["nombre", "marca", "presentacion"]) if (cambia(k) || c.campo === k) cuerpo[k] = vacio(f[k]);
      if (cambia("tamano_valor") || cambia("tamano_unidad") || c.campo === "tamano") {
        cuerpo.tamano_valor = vacio(f.tamano_valor);
        cuerpo.tamano_unidad = vacio(f.tamano_unidad);
      }
      if (cambia("pack_cantidad")) cuerpo.pack_cantidad = f.pack_cantidad === "" ? null : Number(f.pack_cantidad);
      if (f.motivo) cuerpo.motivo = f.motivo;
      await this.intentar(async () => {
        await this.api(`/admin/conflictos/${c.id}/editar`, { method: "POST", body: cuerpo });
        this.avisar("Conflicto resuelto con tus datos");
        this.edicion = null;
        await this.cargar("conflictos");
        if (this.ficha) await this.recargarFicha();
        this.contarPendientes();
      });
    },

    // ---------------------------------------------------- sugerencias
    CAMPOS_SUG: { nombre: "Nombre", marca: "Marca", tamano_valor: "Tamaño", tamano_unidad: "Unidad", pack_cantidad: "Pack de", presentacion: "Presentación" },
    // «actual → sugerido» de cada campo que propone la sugerencia.
    diffSug(sug) {
      return Object.entries(sug.cambios).map(([k, nuevo]) => ({
        campo: this.CAMPOS_SUG[k] || k,
        actual: sug.actual ? sug.actual[k] : null,
        nuevo,
      }));
    },
    async resolverSug(sug, accion) {
      let nota = null;
      if (accion === "rechazar") {
        nota = (prompt("Motivo del rechazo (le llega a quien sugirió):") || "").trim();
        if (nota.length < 3) return this.avisar("El rechazo necesita un motivo", true);
      }
      await this.intentar(async () => {
        await this.api(`/admin/sugerencias/${sug.id}/${accion === "aprobar" ? "aprobar" : "rechazar"}`, {
          method: "POST", body: accion === "aprobar" ? {} : { nota },
        });
        this.avisar(accion === "aprobar" ? "Aprobada y aplicada" : "Rechazada");
        this.quitar("sugerencias", [sug.id]);
        this.contarPendientes(); this.cargarTablero();
      });
    },
    async resolverSugEnMasa(accion) {
      const ids = this.elegidos("sugerencias");
      if (!ids.length) return;
      let nota = null;
      if (accion === "rechazar") {
        nota = (prompt(`Motivo del rechazo de ${ids.length} sugerencia(s):`) || "").trim();
        if (nota.length < 3) return this.avisar("El rechazo necesita un motivo", true);
      } else if (!confirm(`¿Aprobar ${ids.length} sugerencia(s)? Se aplican al catálogo y se bloquean contra el ETL.`)) return;
      await this.intentar(async () => {
        const r = await this.api("/admin/sugerencias/resolver", { method: "POST", body: { ids, accion, nota } });
        this.avisar(r.fallidas.length ? `${r.resueltas} resueltas, ${r.fallidas.length} con error: ${r.fallidas[0].error}` : `${r.resueltas} resueltas`, r.fallidas.length > 0);
        await this.cargar("sugerencias");
        this.contarPendientes(); this.cargarTablero();
      });
    },

    // ------------------------------------------- alta / corrección simple
    formVacio() { return { nombre: "", marca: "", tamano_valor: "", tamano_unidad: "", pack_cantidad: "", presentacion: "" }; },
    async buscarEan() {
      const a = this.alta, ean = a.ean.trim();
      if (!/^[0-9]{8,14}$/.test(ean)) return this.avisar("El EAN son entre 8 y 14 dígitos", true);
      a.buscado = false;
      try {
        const d = await this.api(`/admin/productos/por-ean/${ean}`);
        a.d = d;
        a.b = { nombre: d.nombre, marca: d.marca || "", tamano_valor: d.tamano_valor ?? "", tamano_unidad: d.tamano_unidad || "", pack_cantidad: d.pack_cantidad ?? "", presentacion: d.presentacion || "" };
      } catch (e) {
        if (e.status !== 404) return this.avisar(e.message, true);
        a.d = null; a.b = this.formVacio();  // no existe: es un alta
      }
      a.ean = ean; a.buscado = true;
    },
    async marcasLike() {
      const q = (this.alta.b.marca || "").trim();
      if (q.length < 2) { this.alta.marcas = []; return; }
      try { this.alta.marcas = await this.api(`/admin/catalogo/marcas?q=${encodeURIComponent(q)}`); } catch {}
    },
    cuerpoAlta() {
      const b = this.alta.b, num = (v) => (v === "" || v == null ? null : Number(v));
      const txt = (v) => (String(v ?? "").trim() || null);
      return {
        nombre: txt(b.nombre), marca: txt(b.marca),
        tamano_valor: num(b.tamano_valor), tamano_unidad: b.tamano_unidad || null,
        pack_cantidad: num(b.pack_cantidad), presentacion: txt(b.presentacion),
      };
    },
    async guardarAlta() {
      const a = this.alta;
      a.enviando = true;
      await this.intentar(async () => {
        const cuerpo = this.cuerpoAlta();
        if (a.d) {
          const d = a.d, c = {};
          for (const k of Object.keys(cuerpo)) {
            const antes = d[k] == null ? null : (k === "tamano_valor" ? Number(d[k]) : d[k]);
            if (cuerpo[k] !== antes) c[k] = cuerpo[k];
          }
          if (!Object.keys(c).length) return this.avisar("No hay cambios");
          if ("tamano_valor" in c || "tamano_unidad" in c) { c.tamano_valor = cuerpo.tamano_valor; c.tamano_unidad = cuerpo.tamano_unidad; }
          await this.api(`/admin/productos/${d.id}`, { method: "PATCH", body: c });
          this.avisar("Corregido y bloqueado contra el ETL");
        } else {
          await this.api("/admin/productos", { method: "POST", body: { ean: a.ean, ...cuerpo } });
          this.avisar("Producto dado de alta");
        }
        this.cargarTablero();
        await this.buscarEan();
      });
      a.enviando = false;
    },

    // ----------------------------------------------------- invitaciones
    async generarPines() {
      const p = this.pines;
      const horas = p.sinVencimiento ? null : Math.round(Number(p.n) * (p.unidad === "d" ? 24 : 1));
      p.enviando = true;
      await this.intentar(async () => {
        const r = await this.api("/admin/invitaciones", {
          method: "POST",
          body: { cantidad: Number(p.cantidad), nota: p.nota.trim() || null, vigencia_horas: horas },
        });
        p.nuevos = r;
        this.avisar(r.length === 1 ? "PIN creado" : `${r.length} PINs creados`);
        await this.cargar("invitaciones", true);
      });
      p.enviando = false;
    },
    async revocarPin(i) {
      if (!confirm(`¿Anular el PIN ${i.codigo}? Deja de servir.`)) return;
      await this.intentar(async () => {
        await this.api(`/admin/invitaciones/${i.id}`, { method: "DELETE" });
        this.pines.nuevos = this.pines.nuevos.filter((n) => n.id !== i.id);
        this.avisar("PIN anulado");
        await this.cargar("invitaciones");
      });
    },
    // Los recién creados, uno por línea («482913  Juan»), para pegar en un chat.
    async copiarNuevos() {
      const t = this.pines.nuevos.map((n) => (n.nota ? `${n.codigo}  ${n.nota}` : n.codigo)).join("\n");
      try { await navigator.clipboard.writeText(t); this.avisar("Copiado"); }
      catch { this.avisar("No pude copiar: seleccioná el texto a mano", true); }
    },

    // ----------------------------------------------------------- config
    async cargarConfig() {
      await this.intentar(async () => { this.config = await this.api("/admin/config"); });
    },
    async cargarReglas() {
      await this.intentar(async () => { this.reglas = await this.api("/admin/reglas"); });
    },
    async guardarMensaje(r, texto = r.nuevo) {
      if (texto === undefined) return;
      await this.intentar(async () => {
        const n = await this.api(`/admin/reglas/${r.codigo}`, { method: "PUT", body: { mensaje: texto } });
        Object.assign(r, n, { nuevo: undefined });
        this.avisar(`Mensaje de «${r.titulo}» guardado`);
      });
    },
    async restaurarMensaje(r) { await this.guardarMensaje(r, ""); },
    async cambiarConfig(c, valor) {
      let v = valor;
      if (typeof c.valor === "number") v = Number(valor);
      await this.intentar(async () => {
        try {
          const r = await this.api(`/admin/config/${c.clave}`, { method: "PUT", body: { valor: v } });
          Object.assign(c, r);
          this.avisar(`${c.clave} guardado`);
        } catch (e) { await this.cargarConfig(); throw e; }
      });
    },


    // ------------------------------------------------------------ fichas
    // Una ficha junta TODO lo que se puede hacer con una entidad y pasa por la lógica de
    // negocio del backend (validaciones, efectos, auditoría). La tabla sigue para lo masivo.
    RUTAS: { local: "locales", precio: "precios", usuario: "usuarios", producto: "productos" },

    async abrir(tipo, id) {
      this.ficha = { tipo, id, d: null, b: {}, x: {}, cargando: true };
      await this.recargarFicha();
    },
    async recargarFicha() {
      const f = this.ficha; if (!f) return;
      f.cargando = true;
      try {
        const d = await this.api(`/admin/${this.RUTAS[f.tipo]}/${f.id}`);
        f.d = d; f.b = this.borrador(f.tipo, d); f.x = this.extras(f.tipo, d);
      } catch (e) { this.avisar(e.message, true); this.ficha = null; return; }
      f.cargando = false;
    },
    borrador(tipo, d) {
      if (tipo === "local") return { nombre: d.nombre, direccion: d.direccion || "", lat: d.lat, lng: d.lng };
      if (tipo === "precio") return { precio: d.precio };
      if (tipo === "usuario") return { alias: d.alias };
      return { nombre: d.nombre, marca: d.marca || "", tamano_valor: d.tamano_valor, tamano_unidad: d.tamano_unidad || "", pack_cantidad: d.pack_cantidad ?? "", presentacion: d.presentacion || "" };
    },
    extras(tipo, d) {
      if (tipo === "precio") return { motivo: "", revertir: false };
      if (tipo === "usuario") return { rol: d.rol === "usuario" ? "moderador" : "usuario", motivoRol: "", delta: 1, motivoKarma: "", motivoBaja: "" };
      return {};
    },
    verPrecios(filtros) { this.ficha = null; this.ir('precios', filtros); },
    cerrarFicha() { this.ficha = null; this.cargar(this.actual); if (this.vista === "catalogo") this.cargarTablero(); },
    // Cambia de ficha sin perder la lista de fondo (p. ej. del precio a su local).
    irFicha(tipo, id) { this.abrir(tipo, id); },

    // Hace una acción de negocio, avisa y refresca la ficha.
    async accion(fn, mensaje) {
      try { await fn(); this.avisar(mensaje); await this.recargarFicha(); }
      catch (e) { this.avisar(e.message, true); }
    },
    cambios(tipo) {
      const { d, b } = this.ficha, c = {};
      const num = (v) => (v === "" || v == null ? null : Number(v));
      if (tipo === "local") {
        if (b.nombre.trim() !== d.nombre) c.nombre = b.nombre;
        if ((b.direccion || "") !== (d.direccion || "")) c.direccion = b.direccion.trim() || null;
        if (num(b.lat) !== d.lat || num(b.lng) !== d.lng) { c.lat = num(b.lat); c.lng = num(b.lng); }
      } else if (tipo === "usuario") {
        if (b.alias.trim() !== d.alias) c.alias = b.alias;
      } else if (tipo === "producto") {
        if (b.nombre.trim() !== d.nombre) c.nombre = b.nombre;
        if ((b.marca || "") !== (d.marca || "")) c.marca = b.marca.trim() || null;
        if (num(b.tamano_valor) !== (d.tamano_valor == null ? null : Number(d.tamano_valor)) || (b.tamano_unidad || "") !== (d.tamano_unidad || "")) {
          c.tamano_valor = num(b.tamano_valor); c.tamano_unidad = b.tamano_unidad || null;
        }
        if (num(b.pack_cantidad) !== (d.pack_cantidad ?? null)) c.pack_cantidad = num(b.pack_cantidad);
        if ((b.presentacion || "").trim().toLowerCase() !== (d.presentacion || "")) c.presentacion = b.presentacion.trim() || null;
      }
      return c;
    },
    hayCambios() { const f = this.ficha; return !!f && !!f.d && Object.keys(this.cambios(f.tipo)).length > 0; },

    async guardarFicha() {
      const f = this.ficha, c = this.cambios(f.tipo);
      if (!Object.keys(c).length) return this.avisar("No hay cambios");
      const ruta = `/admin/${this.RUTAS[f.tipo]}/${f.id}`;
      await this.accion(async () => {
        try { await this.api(ruta, { method: "PATCH", body: c }); }
        catch (e) {
          // El backend sospecha un duplicado: el admin decide si es otro local de verdad.
          if (e.status === 409 && e.detalle?.codigo === "local_duplicado" &&
              confirm(e.message + "\n\n¿Es otro local distinto? Aceptar guarda igual.")) {
            await this.api(ruta, { method: "PATCH", body: { ...c, forzar: true } });
          } else throw e;
        }
      }, "Guardado");
    },
    async guardarPrecio() {
      const f = this.ficha;
      await this.accion(() => this.api(`/admin/precios/${f.id}`, { method: "PATCH", body: { precio: f.b.precio, motivo: f.x.motivo || null } }), "Precio corregido");
    },
    async borrarPrecioFicha() {
      const f = this.ficha;
      if (!confirm("¿Borrar este precio? Queda el rastro en Auditoría.")) return;
      const q = new URLSearchParams({ revertir_karma: f.x.revertir });
      if (f.x.motivo) q.set("motivo", f.x.motivo);
      await this.intentar(async () => {
        await this.api(`/admin/precios/${f.id}?${q}`, { method: "DELETE" });
        this.avisar("Precio borrado"); this.cerrarFicha();
      });
    },

    // --- local
    validarFicha() { return this.accion(() => this.api("/admin/locales/validar", { method: "POST", body: { ids: [this.ficha.id] } }), "Local validado"); },
    quitarValidacion() { return this.accion(() => this.api(`/admin/locales/${this.ficha.id}`, { method: "PATCH", body: { verificado: false } }), "Verificación quitada"); },
    async fusionarFicha(dup, esteEnAquel) {
      const f = this.ficha;
      const txt = esteEnAquel ? `Fusionar ESTE local en «${dup.nombre}»? Este se borra y sus precios pasan al otro.`
                              : `Fusionar «${dup.nombre}» en ESTE local? El otro se borra y sus precios pasan a este.`;
      if (!confirm(txt)) return;
      const body = esteEnAquel ? { destino_id: dup.id, origen_ids: [f.id] } : { destino_id: f.id, origen_ids: [dup.id] };
      await this.intentar(async () => {
        await this.api("/admin/locales/fusionar", { method: "POST", body });
        this.avisar("Fusionados");
        if (esteEnAquel) await this.abrir("local", dup.id); else await this.recargarFicha();
      });
    },
    async borrarLocalFicha() {
      if (!confirm("¿Borrar este local?")) return;
      await this.intentar(async () => {
        const r = await this.api("/admin/locales/borrar", { method: "POST", body: { ids: [this.ficha.id] } });
        if (!r.afectados) return this.avisar(r.motivo, true);
        this.avisar("Local borrado"); this.cerrarFicha();
      });
    },

    // --- usuario
    cambiarRolFicha() {
      const x = this.ficha.x;
      if (!confirm(`¿Cambiar el rol a «${x.rol}»?`)) return;
      return this.accion(() => this.api(`/admin/usuarios/${this.ficha.id}/rol`, { method: "POST", body: { rol: x.rol, motivo: x.motivoRol || null } }), "Rol cambiado");
    },
    ajustarKarmaFicha() {
      const x = this.ficha.x;
      return this.accion(() => this.api(`/admin/usuarios/${this.ficha.id}/karma`, { method: "POST", body: { delta: Number(x.delta), motivo: x.motivoKarma } }), "Karma ajustado");
    },

    darBajaFicha() {
      const x = this.ficha.x;
      if (!confirm(`¿Dar de baja a ${this.ficha.d.alias}? Pierde el acceso en el próximo pedido (se puede revertir).`)) return;
      return this.accion(() => this.api(`/admin/usuarios/${this.ficha.id}/baja`, { method: "POST", body: { motivo: x.motivoBaja } }), "Usuario dado de baja");
    },
    reactivarFicha() {
      const x = this.ficha.x;
      return this.accion(() => this.api(`/admin/usuarios/${this.ficha.id}/reactivar`, { method: "POST", body: { motivo: x.motivoBaja } }), "Usuario reactivado");
    },
    // Estado + escalón en una sola insignia (la baja manda sobre el karma).
    insignia(u) {
      if (u.estado === "baja") return { texto: "de baja", clase: "baja" };
      if (u.escalon === "restringido") return { texto: "restringido", clase: "baja" };
      if (u.escalon === "aviso") return { texto: "aviso", clase: "aviso" };
      return { texto: "normal", clase: "ok" };
    },

    // --- producto
    desbloquear(campo) {
      return this.accion(() => this.api(`/admin/productos/${this.ficha.id}/desbloquear`, { method: "POST", body: { campos: [campo] } }), `${campo} desbloqueado`);
    },
    resolverFicha(c, elegido) {
      return this.accion(() => this.api(`/admin/conflictos/${c.id}/resolver`, { method: "POST", body: { elegido } }), "Conflicto resuelto").then(() => this.contarPendientes());
    },


    // -------------------------------------------------------------- ETL
    async iniciarEtl() {
      if (!this.etlDefs.length) await this.intentar(async () => { this.etlDefs = await this.api("/admin/etl"); });
      await this.cargar("etl");
      // Mientras haya algo en cola o corriendo, el historial (y el log abierto) se refresca solo.
      this._etlTimer = setInterval(() => this.refrescarEtl(), 3000);
    },
    async refrescarEtl() {
      if (this.vista !== "etl") return clearInterval(this._etlTimer);
      const activo = (e) => e && ["en_cola", "corriendo", "cancelando"].includes(e.estado);
      if (this.sec.etl.items.some(activo) || activo(this.etlDetalle)) {
        try {
          const d = await this.api(`/admin/etl/ejecuciones?${this.query("etl")}`);
          this.sec.etl.items = d.items; this.sec.etl.total = d.total;
          if (this.etlDetalle) this.etlDetalle = await this.api(`/admin/etl/ejecuciones/${this.etlDetalle.id}`);
        } catch {}
      }
    },
    get etlDef() { return this.etlDefs.find((d) => d.clave === this.etlClave); },
    elegirEtl(clave) {
      this.etlClave = clave; this.etlArchivos = {};
      this.etlForm = {};
      for (const p of this.etlDef?.parametros || []) {
        if (p.tipo === "booleano") this.etlForm[p.nombre] = p.default === true;
        else this.etlForm[p.nombre] = p.default ?? "";
      }
    },
    async subirArchivoEtl(p, evento) {
      const f = evento.target.files[0];
      if (!f) return;
      this.etlSubiendo = true;
      await this.intentar(async () => {
        const a = await this.api(`/admin/etl/archivos?nombre=${encodeURIComponent(f.name)}`, { method: "POST", crudo: f });
        this.etlArchivos[p.nombre] = a; this.etlForm[p.nombre] = a.id;
        this.avisar(`Archivo subido (${this.kb(a.tamano)}): se borra al importar de verdad o a las 24 h`);
      });
      this.etlSubiendo = false;
      evento.target.value = "";
    },
    parametrosEtl() {
      // Solo lo que se completó: lo vacío lo resuelve el default del backend.
      return Object.fromEntries(Object.entries(this.etlForm).filter(([, v]) => v !== "" && v != null));
    },
    async ejecutarEtl(clave = this.etlClave, parametros = this.parametrosEtl()) {
      this.etlEnviando = true;
      await this.intentar(async () => {
        const e = await this.api(`/admin/etl/${clave}/ejecutar`, { method: "POST", body: { parametros } });
        this.avisar(e.ejecutor === "local" ? "En cola: la toma el worker local (make etl-worker en tu máquina)" : "En cola: corre en el backend");
        await this.cargar("etl", true);
        this.etlDetalle = e;
        this.refrescarEtl();
      });
      this.etlEnviando = false;
    },
    // Tras un simulacro ok: la misma ejecución, pero escribiendo.
    repetirAplicando(e) {
      return this.ejecutarEtl(e.etl, { ...e.parametros, aplicar: true });
    },
    puedeAplicar(e) {
      const d = this.etlDefs.find((x) => x.clave === e.etl);
      return e.estado === "ok" && d?.consume_archivo_con === "aplicar" && !e.parametros.aplicar;
    },
    async verEtl(e) {
      await this.intentar(async () => { this.etlDetalle = await this.api(`/admin/etl/ejecuciones/${e.id}`); });
    },
    async cancelarEtl(e) {
      if (!confirm("¿Cancelar esta ejecución? Lo ya cargado por lotes se queda (cada lote es una transacción).")) return;
      await this.intentar(async () => {
        await this.api(`/admin/etl/ejecuciones/${e.id}/cancelar`, { method: "POST" });
        this.avisar("Cancelación pedida");
        await this.cargar("etl");
        if (this.etlDetalle?.id === e.id) await this.verEtl(e);
      });
    },
    etlClase(estado) { return { ok: "ok", fallo: "baja", cancelada: "aviso", cancelando: "aviso", corriendo: "mal", en_cola: "" }[estado] || ""; },
    etlTitulo(e) { return e.titulo || e.etl; },
    etlDuracion(e) {
      if (!e.iniciado_en) return "";
      const s = Math.round(((e.terminado_en ? new Date(e.terminado_en) : new Date()) - new Date(e.iniciado_en)) / 1000);
      return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${s % 60} s`;
    },
    kb(b) { return b > 1048576 ? (b / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(b / 1024)) + " KB"; },
    resumenParametros(e) {
      return Object.entries(e.parametros).map(([k, v]) => `${k}=${v && v.nombre ? v.nombre : v}`).join(" · ");
    },

    // ------------------------------------------------------------ varios
    corto(id) { return id ? String(id).slice(0, 8) : ""; },
    fecha(f) { return f ? new Date(f).toLocaleString("es-AR", { dateStyle: "short", timeStyle: "short" }) : ""; },
    mapa(l) { return `https://www.openstreetmap.org/?mlat=${l.lat}&mlon=${l.lng}#map=18/${l.lat}/${l.lng}`; },
    json(o) { return o ? JSON.stringify(o) : ""; },
  };
}
