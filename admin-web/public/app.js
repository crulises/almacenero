// Panel de admin de Almacenero. Habla SOLO con el backend (/v1/admin).
// Alpine.js (CDN) + fetch; sin build. Todo el estado vive en `panel()`.

const API = window.API_URL;
const CLAVE = "almacenero_admin_sesion";

const SECCIONES = {
  locales: { ruta: "/admin/locales", filtros: { verificado: "", fuente: "", q: "", sin_precios: false, orden: "alta" } },
  usuarios: { ruta: "/admin/usuarios", filtros: { tipo: "", rol: "", q: "", orden: "alta" } },
  precios: { ruta: "/admin/precios", filtros: { local_id: "", ean: "", user_id: "", desde: "", hasta: "" } },
  productos: { ruta: "/admin/productos", filtros: { q: "", origen: "", con_conflictos: false } },
  conflictos: { ruta: "/admin/conflictos", filtros: { estado: "pendiente" } },
  auditoria: { ruta: "/admin/auditoria", filtros: { entidad: "" } },
};

const TITULOS = {
  locales: "Locales", usuarios: "Usuarios", precios: "Precios", productos: "Productos",
  conflictos: "Conflictos del catálogo", config: "Configuración", auditoria: "Auditoría",
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
    vista: "locales",
    login: { email: "", password: "", error: "", enviando: false },
    config: [],
    destino: "",
    toast: null,
    _t: null,

    init() { if (this.sesion) this.cambiarVista("locales"); },

    // ------------------------------------------------------------- red
    async api(path, { method = "GET", body } = {}, reintento = true) {
      const r = await fetch(API + "/v1" + path, {
        method,
        headers: {
          Authorization: "Bearer " + this.sesion.access_token,
          ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        },
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });
      if (r.status === 401 && reintento && (await this.renovar())) return this.api(path, { method, body }, false);
      if (r.status === 401) { this.salir(); throw new Error("La sesión venció: entrá de nuevo"); }
      if (r.status === 204) return null;
      const datos = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(this.mensaje(datos.detail) || `Error ${r.status}`);
      return datos;
    },
    mensaje(d) {
      if (!d) return "";
      if (typeof d === "string") return d;
      if (Array.isArray(d)) return d.map((e) => `${(e.loc || []).slice(1).join(".")}: ${e.msg}`).join("; ");
      return d.mensaje || JSON.stringify(d);
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
        this.cambiarVista("locales");
      } catch (e) {
        this.login.error = e instanceof TypeError ? "No puedo conectar con el backend (" + API + ")" : e.message;
      } finally { this.login.enviando = false; }
    },
    salir() {
      this.sesion = null;
      try { localStorage.removeItem(CLAVE); } catch {}
    },

    // ------------------------------------------------------- navegación
    cambiarVista(v) {
      this.vista = v;
      if (v === "config") this.cargarConfig(); else this.cargar(v);
    },
    ir(vista, filtros) {
      Object.assign(this.sec[vista].f, filtros);
      this.sec[vista].offset = 0;
      this.cambiarVista(vista);
    },

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
        } catch (e) { await this.cargar(this.vista); throw e; }
      });
    },
    local(l, campo, valor) { return this.parchar(`/admin/locales/${l.id}`, l, { [campo]: valor.trim() || null }); },
    ubicacion(l, lat, lng) {
      if (isNaN(lat) || isNaN(lng)) return this.avisar("Ubicación inválida", true);
      return this.parchar(`/admin/locales/${l.id}`, l, { lat, lng });
    },
    alias(u, valor) { return this.parchar(`/admin/usuarios/${u.id}`, u, { alias: valor }); },
    monto(p, valor) { return this.parchar(`/admin/precios/${p.id}`, p, { precio: valor }); },
    producto(p, campos) { return this.parchar(`/admin/productos/${p.id}`, p, campos); },

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
      });
    },

    // ----------------------------------------------------------- config
    async cargarConfig() {
      await this.intentar(async () => { this.config = await this.api("/admin/config"); });
    },
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

    // ------------------------------------------------------------ varios
    corto(id) { return id ? String(id).slice(0, 8) : ""; },
    fecha(f) { return f ? new Date(f).toLocaleString("es-AR", { dateStyle: "short", timeStyle: "short" }) : ""; },
    mapa(l) { return `https://www.openstreetmap.org/?mlat=${l.lat}&mlon=${l.lng}#map=18/${l.lat}/${l.lng}`; },
    json(o) { return o ? JSON.stringify(o) : ""; },
  };
}
