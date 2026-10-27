"""Idempotent first-install initialization for existing websites."""


def post_init_hook(env):
    Config = env['flexsys.career.config'].sudo()
    Pool = env['hr.talent.pool'].sudo()
    for website in env['website'].sudo().search([]):
        config = Config.search([('website_id', '=', website.id)], limit=1)
        if not config:
            config = Config.with_company(website.company_id).create({
                'website_id': website.id, 'company_id': website.company_id.id,
            })
        if not config.default_talent_pool_id:
            pool = Pool.with_company(website.company_id).create({
                'name': '%s — General Applications' % website.company_id.name,
                'company_id': website.company_id.id,
            })
            config.default_talent_pool_id = pool
        Cat = env['flexsys.career.category'].sudo().with_company(website.company_id)
        category_names = ['Barista', 'Cashier', 'Customer Service', 'Food Preparation',
                          'Pastry and Desserts', 'Branch Management', 'Operations',
                          'Accounting', 'Purchasing', 'Inventory', 'Administration', 'Other']
        for idx, name in enumerate(category_names):
            if not Cat.search([('name', '=', name), ('company_id', '=', website.company_id.id)], limit=1):
                Cat.create({'name': name, 'sequence': (idx + 1) * 10,
                            'company_id': website.company_id.id})
