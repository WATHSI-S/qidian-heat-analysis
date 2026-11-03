import uvicorn

if __name__ == '__main__':
    from scripts.build_site import build_site
    build_site()
    uvicorn.run('workbench.app:app', host='127.0.0.1', port=8765)
