"""Initialize standalone careers for the current database company.

Other companies can have separate configurations. Only the server-selected
one serves the shared /careers path.
"""


def post_init_hook(env):
    company = env.company
    Config = env['flexsys.career.config'].sudo()
    Pool = env['hr.talent.pool'].sudo()
    config = Config.search([('company_id', '=', company.id)], limit=1)
    if not config:
        config = Config.with_company(company).create({'company_id': company.id})
    if not config.default_talent_pool_id:
        pool = Pool.with_company(company).create({
            'name': '%s — General Applications' % company.name,
            'company_id': company.id,
        })
        config.default_talent_pool_id = pool
    Cat = env['flexsys.career.category'].sudo().with_company(company)
    category_names = [
        'Barista', 'Cashier', 'Customer Service', 'Food Preparation',
        'Pastry and Desserts', 'Branch Management', 'Operations',
        'Accounting', 'Purchasing', 'Inventory', 'Administration', 'Other',
    ]
    for idx, name in enumerate(category_names):
        if not Cat.search([('name', '=', name), ('company_id', '=', company.id)], limit=1):
            Cat.create({'name': name, 'sequence': (idx + 1) * 10,
                        'company_id': company.id})
    # Do not clobber an explicitly selected company after a module reinstall.
    ICP = env['ir.config_parameter'].sudo()
    if not ICP.get_param('flexsys_recruitment_portal.public_config_id'):
        ICP.set_param('flexsys_recruitment_portal.public_config_id', str(config.id))
