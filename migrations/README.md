# Migrations — Alembic

## Crear una nueva migración
```
alembic revision --autogenerate -m "descripcion"
```

## Aplicar migraciones
```
alembic upgrade head
```

## Revertir última migración
```
alembic downgrade -1
```
