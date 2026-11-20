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
  invitaciones: { ruta: "/admin/invitaciones", filtros: { estado: "", q: "" } },
  auditoria: { ruta: "/admin/auditoria", filtros: { entidad: "" } },
};

const TITULOS = {
  locales: "Locales", usuarios: "Usuarios", invitaciones: "Invitaciones", precios: "Precios", catalogo: "Catálogo",
  config: "Configuración", auditoria: "Auditoría",
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
    subcatalogo: "productos",  // dentro de Catálogo: productos | conflictos
    login: { email: "", password: "", error: "", enviando: false },
    config: [],
    pendientes: 0,  // conflictos del catálogo sin resolver (globito de Catálogo)
    destino: "",
    // Generador de PINs de invitación (un solo uso). `nuevos` = los recién creados.
    pines: { cantidad: 1, nota: "", n: 24, unidad: "h", sinVencimiento: false, nuevos: [], enviando: false },
    ficha: null,
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
    // Sección cuyos datos se están viendo (Catálogo agrupa productos y conflictos).
    get actual() { return this.vista === "catalogo" ? this.subcatalogo : this.vista; },
    cambiarVista(v) {
      this.vista = v;
      if (v === "config") this.cargarConfig(); else this.cargar(v === "catalogo" ? this.subcatalogo : v);
      if (v === "catalogo") this.contarPendientes();
    },
    async contarPendientes() {
      try { this.pendientes = (await this.api("/admin/conflictos?estado=pendiente&limit=1")).total; } catch {}
    },
    irCatalogo(sub) { this.subcatalogo = sub; this.cambiarVista("catalogo"); },
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
        this.contarPendientes();
      });
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
      return { nombre: d.nombre, marca: d.marca || "", tamano_valor: d.tamano_valor, tamano_unidad: d.tamano_unidad || "" };
    },
    extras(tipo, d) {
      if (tipo === "precio") return { motivo: "", revertir: false };
      if (tipo === "usuario") return { rol: d.rol === "admin" ? "usuario" : "admin", motivoRol: "", delta: 1, motivoKarma: "" };
      return {};
    },
    verPrecios(filtros) { this.ficha = null; this.ir('precios', filtros); },
    cerrarFicha() { this.ficha = null; this.cargar(this.actual); },
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

    // --- producto
    desbloquear(campo) {
      return this.accion(() => this.api(`/admin/productos/${this.ficha.id}/desbloquear`, { method: "POST", body: { campos: [campo] } }), `${campo} desbloqueado`);
    },
    resolverFicha(c, elegido) {
      return this.accion(() => this.api(`/admin/conflictos/${c.id}/resolver`, { method: "POST", body: { elegido } }), "Conflicto resuelto").then(() => this.contarPendientes());
    },

    // ------------------------------------------------------------ varios
    corto(id) { return id ? String(id).slice(0, 8) : ""; },
    fecha(f) { return f ? new Date(f).toLocaleString("es-AR", { dateStyle: "short", timeStyle: "short" }) : ""; },
    mapa(l) { return `https://www.openstreetmap.org/?mlat=${l.lat}&mlon=${l.lng}#map=18/${l.lat}/${l.lng}`; },
    json(o) { return o ? JSON.stringify(o) : ""; },
  };
}
