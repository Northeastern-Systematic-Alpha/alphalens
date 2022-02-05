import pandas as pd

ADJUSTOR_FIELDS = {
    'crsp.security_daily': [
        {
            'adjustor': 'cfacpr',
            'fields_to_adjust': ['prc', 'openprc', 'askhi', 'bidlo', 'bid', 'ask'],
            'operation': '/',
            'function': 'abs'
        },
        {
            'adjustor': 'cfacshr',
            'fields_to_adjust': ['vol', 'shrout'],
            'operation': '*'
        }
    ]
}


def adjust_crsp_data(frame: pd.DataFrame) -> pd.DataFrame:
    """
    utility function to adjust CRSP pricing data.
    frame must have column "cfacpr" to adjust any price related column.
    frame must have column "cfacshr" to adjust and share related data
    configured to adjust: ['prc', 'openprc', 'askhi', 'bidlo', 'bid', 'ask', 'vol', 'shrout']

    Will make al columns lowe case!!!!!

    :param frame: the dataframe with the pricing data to adjust
    :return: passed frame with the pricing data adjusted
    """
    frame = frame.copy()
    frame.columns = [col.lower() for col in frame.columns]

    adjustment = '\n'.join([_adjust_field(field=col, table='crsp.security_daily') for col in frame.columns])

    if adjustment == '':
        print('NO COLUMNS ADJUSTED')
        return frame

    return frame.eval(adjustment)

def _adjust_field(field: str, table: str) -> str:
    """
    Makes the pandas eval string to adjust a given field.
    If there's no adjustment to be done then it will just return an empty string
    :param field: the single field we want to adjust
    :param table: the table the field is apart of
    """
    table_adj = ADJUSTOR_FIELDS.get(table.lower())

    if table_adj is None:
        raise ValueError(f'Table {table} is not in ADJUSTOR_FIELDS. '
                         f'Valid tables are {list(ADJUSTOR_FIELDS.keys())}')

    for diff_adj in table_adj:
        fields_to_adjust = diff_adj.get('fields_to_adjust')
        function = diff_adj.get('function')
        wanted_diff_adj = field in fields_to_adjust

        if wanted_diff_adj and function:
            return (f'{field} = {diff_adj["function"]}({field} {diff_adj["operation"]} '
                    f'{diff_adj["adjustor"]})')

        if wanted_diff_adj:
            return f'{field} = {field} {diff_adj["operation"]} {diff_adj["adjustor"]}'

    return ''


if __name__ == '__main__':
    df = pd.read_csv('/Users/alex/Desktop/WRDS/CRSP/Annual Update/Stock : Security Files/Daily Stock File/Daily Stock File 29251231-20211231.gz', nrows=1000).drop('cfacshr', axis=1)
    print(adjust_crsp_data(df))