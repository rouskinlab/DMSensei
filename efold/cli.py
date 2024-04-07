import json
import click
from efold.api.run import run

@click.command('efold')
@click.argument('sequence', required=False, type=str)
@click.option('--seq', '-s', help='Input RNA sequence', type=str, multiple=True)
@click.option('--fasta', '-f', help='Input FASTA file path')
@click.option('--output', '-o', default='output.txt', help='Output file path (json, txt or csv)', type=click.Path())
@click.option('--basepair/--dotbracket', '-bp/-db', default=False, help='Output structure format')
def cli(sequence, seq, fasta, output, basepair):
    fmt = 'bp' if basepair else 'dotbracket'
    if seq:
        result = run(seq, fmt)
    elif sequence:
        result = run(sequence, fmt)
    elif fasta:
        result = run(fasta, fmt)
    else:
        click.echo("Please provide either a sequence or a FASTA file.")
        return

    with open(output, 'w') as f:
        file_fmt = output.split('.')[-1]
        if file_fmt == 'json':
            f.write(json.dumps(result, indent=4))
        elif file_fmt == 'csv':
            import csv
            writer = csv.writer(f)
            writer.writerows(result.items())
        else:
            for seq, struct in result.items():
                f.write(f"{seq}\n{struct}\n\n")
        for seq, struct in result.items():
            click.echo(seq)
            click.echo(struct)
            click.echo()
    click.echo(f"Output saved to {output}")

if __name__ == '__main__':
    cli()